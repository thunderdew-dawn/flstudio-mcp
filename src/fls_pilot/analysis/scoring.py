"""Shared score helpers for analysis workflow reports."""

from __future__ import annotations


def clamp_score(value: float | int | None, *, default: int = 0) -> int:
    """Clamp a numeric score to the public 0..100 range."""
    if value is None:
        return default
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return default
    return max(0, min(100, round(numeric)))


def health_from_risk(risk_score: float | int | None) -> int:
    """Convert risk into the canonical health direction: high is good."""
    return 100 - clamp_score(risk_score)


def coverage_score(required: int, available: int) -> int:
    """Percent of required evidence currently available."""
    required = max(0, int(required))
    available = max(0, int(available))
    if required == 0:
        return 100
    return clamp_score((available / required) * 100)


def risk_band(score: float | int | None) -> str:
    """Map 0..100 risk to a stable band."""
    value = clamp_score(score)
    if value == 0:
        return "none"
    if value <= 25:
        return "low"
    if value <= 60:
        return "medium"
    if value <= 85:
        return "high"
    return "critical"


def confidence_band(score: float | int | None) -> str:
    """Map 0..100 confidence to a stable band."""
    value = clamp_score(score)
    if value < 40:
        return "low"
    if value < 75:
        return "medium"
    return "high"


def risk_from_severities(severities: list[str] | tuple[str, ...]) -> int:
    """Estimate aggregate risk from finding severities."""
    weights = {
        "critical": 45,
        "high": 32,
        "error": 32,
        "medium": 16,
        "warning": 12,
        "low": 6,
        "info": 2,
        "ok": 0,
    }
    return clamp_score(sum(weights.get(str(item).lower(), 0) for item in severities))


def weighted_mix_review_risk(
    findings: list[object] | tuple[object, ...],
    *,
    genre_profile: str | None = None,
    levels_valid: bool = True,
) -> tuple[int, list[dict[str, object]]]:
    """Estimate Mix Review risk from severity, evidence strength, and user decisions.

    The score stays additive and bounded for legacy compatibility, but it avoids
    treating a static suspicion, live-meter warning, and rendered/stem-backed
    finding as equally strong evidence.
    """
    inputs: list[dict[str, object]] = []
    total = 0.0
    profile = str(genre_profile or "default").strip().lower() or "default"
    for row in findings:
        severity = _row_value(row, "severity", "info")
        rule_id = _row_value(row, "rule", _row_value(row, "rule_id", _row_value(row, "id", "")))
        metadata = _row_metadata(row)
        finding_state = str(metadata.get("finding_state") or "").strip().lower()
        evidence_level = _coerce_int(metadata.get("evidence_level"), default=1)
        evidence_weight = _mix_review_evidence_weight(finding_state, evidence_level, metadata)
        decision_modifier = _mix_review_decision_modifier(metadata)
        rule_weight = _mix_review_rule_weight(str(rule_id), profile)
        contribution = (
            _mix_review_severity_weight(str(severity))
            * evidence_weight
            * rule_weight
            * decision_modifier
        )
        contribution = max(0.0, contribution)
        total += contribution
        inputs.append(
            {
                "id": str(_row_value(row, "id", rule_id)),
                "rule": str(rule_id),
                "severity": str(severity),
                "evidence_level": evidence_level,
                "finding_state": finding_state or "metadata_suspected",
                "evidence_weight": round(evidence_weight, 3),
                "rule_weight": round(rule_weight, 3),
                "decision_modifier": round(decision_modifier, 3),
                "risk_contribution": clamp_score(contribution),
            }
        )
    if not levels_valid:
        total += 4.0
        inputs.append(
            {
                "id": "mix_review.levels_valid",
                "rule": "levels_valid",
                "severity": "info",
                "evidence_level": 1,
                "finding_state": "requires_more_evidence",
                "evidence_weight": 0.2,
                "rule_weight": 1.0,
                "decision_modifier": 1.0,
                "risk_contribution": 4,
            }
        )
    return clamp_score(total), inputs


def _mix_review_severity_weight(severity: str) -> float:
    return {
        "critical": 45.0,
        "error": 32.0,
        "high": 32.0,
        "medium": 16.0,
        "warning": 12.0,
        "low": 6.0,
        "info": 2.0,
        "ok": 0.0,
    }.get(severity.strip().lower(), 2.0)


def _mix_review_evidence_weight(
    finding_state: str,
    evidence_level: int,
    metadata: dict[str, object],
) -> float:
    if finding_state in {"rejected_by_user", "ignored_by_user"}:
        return 0.0
    if finding_state in {"accepted_by_user", "user_confirmed", "stem_audio_confirmed"}:
        return 1.0
    if finding_state == "rendered_master_proxy" or bool(metadata.get("proxy_evidence")):
        return 0.68
    if finding_state == "live_meter_supported":
        return 0.78
    if finding_state in {"name_based_unconfirmed", "static_heuristic"}:
        return 0.35
    if finding_state in {"metadata_suspected", "requires_more_evidence"}:
        return 0.45
    return {1: 0.45, 2: 0.78, 3: 0.68, 4: 1.0}.get(evidence_level, 0.45)


def _mix_review_rule_weight(rule_id: str, profile: str) -> float:
    rule = rule_id.strip().lower()
    weight = 1.0
    if any(token in rule for token in ("clipping", "headroom")):
        weight = 1.15
    if any(token in rule for token in ("low_end", "kick", "bass", "sub")):
        weight = 1.2
    if profile == "psytrance" and any(
        token in rule for token in ("low_end", "kick", "bass", "sub", "bus_headroom")
    ):
        weight *= 1.25
    return weight


def _mix_review_decision_modifier(metadata: dict[str, object]) -> float:
    decision = str(
        metadata.get("user_decision") or metadata.get("decision") or ""
    ).strip().lower()
    state = str(metadata.get("finding_state") or "").strip().lower()
    if decision in {"rejected", "ignored"} or state in {"rejected_by_user", "ignored_by_user"}:
        return 0.0
    if decision == "accepted" or state in {"accepted_by_user", "user_confirmed"}:
        return 1.1
    if metadata.get("human_validation_required") is True:
        return 0.75
    return 1.0


def _row_metadata(row: object) -> dict[str, object]:
    metadata = row.get("metadata") if isinstance(row, dict) else getattr(row, "metadata", None)
    return dict(metadata) if isinstance(metadata, dict) else {}


def _row_value(row: object, key: str, default: object = None) -> object:
    if isinstance(row, dict):
        return row.get(key, default)
    return getattr(row, key, default)


def _coerce_int(value: object, *, default: int) -> int:
    if isinstance(value, bool):
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def confidence_from_coverage(
    *,
    required: int,
    available: int,
    evidence_mode: str,
) -> int:
    """Estimate confidence from required evidence coverage and evidence mode."""
    base = coverage_score(required, available)
    mode_bonus = {
        "rendered_audio": 15,
        "hybrid": 10,
        "watch_window": 8,
        "live_runtime": 4,
        "static_snapshot": 0,
        "manual_check": -10,
    }.get(str(evidence_mode), 0)
    return clamp_score(base + mode_bonus)


def mix_health_score(
    *,
    high: int,
    medium: int,
    low: int,
    levels_valid: bool,
    master_peak: float | None,
) -> int:
    """Calculate health score for Mix Review workflow."""
    penalty = high * 18 + medium * 9 + low * 3
    if not levels_valid:
        penalty += 12
    if master_peak is not None:
        if master_peak >= 0:
            penalty += 24
        elif master_peak > -1:
            penalty += 16
        elif master_peak > -3:
            penalty += 7
    return clamp_score(100 - penalty)


def organizer_score(
    *,
    unnamed_channels: int,
    routing_cleanup: int,
    unnamed_patterns: int,
    unnamed_playlist_tracks: int,
    duplicate_mixer: int,
    duplicate_patterns: int,
    grouping_candidates: int,
) -> int:
    """Calculate health score for Project Organizer workflow."""
    penalty = (
        routing_cleanup * 12
        + unnamed_channels * 5
        + unnamed_patterns * 4
        + unnamed_playlist_tracks * 2
        + duplicate_mixer * 5
        + duplicate_patterns * 4
        + grouping_candidates * 3
    )
    return clamp_score(100 - penalty)


def routing_health_score(
    *,
    direct_count: int,
    unrouted_count: int,
    dead_end_count: int,
    unused_count: int,
) -> int:
    """Calculate health score for Routing Audit workflow."""
    penalty = direct_count * 7 + unrouted_count * 12 + dead_end_count * 14 + unused_count * 3
    return clamp_score(100 - penalty)


def low_end_health_score(
    *,
    high: int,
    medium: int,
    low: int,
    stereo_risks: int,
    levels_valid: bool,
) -> int:
    """Calculate health score for Low-End Analysis workflow."""
    penalty = high * 24 + medium * 12 + low * 4 + stereo_risks * 5 + (0 if levels_valid else 8)
    return clamp_score(100 - penalty)

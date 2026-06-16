"""Routing analysis report helpers."""

from __future__ import annotations

from typing import Any

from .canonical import channel_entity_id, mixer_entity_id
from .schema import AnalysisReport, Coverage, EntityRef, Finding, Freshness, Prerequisite
from .scoring import confidence_from_coverage, risk_from_severities

ROUTING_POLICY_NOTES = (
    "Preserve recognizable existing routing structure before proposing cleanup.",
    "Infer Channel Rack to Mixer relationships from channel target tracks.",
    "Treat plugin insertion, external inputs, and UI drag-and-drop routing as manual guidance.",
)


def routing_analysis_report_from_legacy_payload(
    payload: dict[str, Any],
    *,
    workflow: str,
    title: str,
    created_at: str | None = None,
) -> AnalysisReport:
    """Build a shared analysis report from an existing routing payload."""
    ok = bool(payload.get("ok", True))
    summary = dict(payload.get("summary") or {})
    findings = [dict(row) for row in payload.get("findings") or [] if isinstance(row, dict)]
    details = dict(payload.get("details") or {})
    coverage = _routing_coverage(ok=ok, payload=payload, details=details)
    confidence = confidence_from_coverage(
        required=coverage.required,
        available=coverage.available,
        evidence_mode="static_snapshot",
    )
    risk = risk_from_severities(tuple(row.get("severity", "info") for row in findings))
    analysis_findings = tuple(
        _routing_finding(row, index=index, confidence_score=confidence)
        for index, row in enumerate(findings, start=1)
    )
    return AnalysisReport(
        workflow=workflow,
        title=title,
        analysis_mode="static_snapshot",
        created_at=created_at or str(payload.get("generated_at") or ""),
        freshness=Freshness(
            status="fresh" if ok and coverage.status == "fresh" else coverage.status,
            details="Read-only routing matrix and channel target metadata.",
        ),
        coverage=coverage,
        prerequisites=(
            Prerequisite(
                "fl_session_alive",
                "ok" if ok else "unavailable",
                None if ok else str(payload.get("error") or "Routing data unavailable."),
            ),
            Prerequisite("channel_routing_snapshot", "ok" if ok else "unavailable"),
            Prerequisite("routing_snapshot", "ok" if ok else "unavailable"),
        ),
        risk_score=risk,
        confidence_score=confidence,
        findings=analysis_findings,
        assumptions=(
            "Channel Rack to mixer relationships are inferred from target mixer tracks.",
        ),
        limitations=(
            "Routing review is static metadata evidence; it does not prove audible signal flow.",
            "Plugin insertion, external inputs, and UI drag-and-drop routing remain manual.",
        ),
        next_actions=(
            {
                "type": "workflow",
                "id": "routing_cleanup_plan",
                "label": "Plan cleanup only after reviewing the static routing evidence.",
            },
        ),
        safety={"read_only": True, "project_changes": False},
        metadata={
            "routing_summary": summary,
            "policy_notes": list(details.get("policy_notes") or ROUTING_POLICY_NOTES),
            "template_context": details.get("template_context") or payload.get("template_context"),
        },
    )


def _routing_coverage(
    *,
    ok: bool,
    payload: dict[str, Any],
    details: dict[str, Any],
) -> Coverage:
    required = 3
    if not ok:
        return Coverage(
            required=required,
            available=0,
            missing=("fl_session_alive", "channel_routing_snapshot", "routing_snapshot"),
        )
    missing = []
    available = 1
    if _has_channel_evidence(payload, details):
        available += 1
    else:
        missing.append("channel_routing_snapshot")
    if _has_routing_evidence(payload, details):
        available += 1
    else:
        missing.append("routing_snapshot")
    return Coverage(required=required, available=available, missing=tuple(missing))


def _has_channel_evidence(payload: dict[str, Any], details: dict[str, Any]) -> bool:
    summary = dict(payload.get("summary") or {})
    return (
        "channels" in summary
        or bool(details.get("channels"))
        or bool(payload.get("unrouted_channels"))
        or bool(payload.get("generators_direct_to_master"))
    )


def _has_routing_evidence(payload: dict[str, Any], details: dict[str, Any]) -> bool:
    summary = dict(payload.get("summary") or {})
    return "routes" in summary or "mixer_tracks" in summary or bool(details.get("routes"))


def _routing_finding(
    row: dict[str, Any],
    *,
    index: int,
    confidence_score: int,
) -> Finding:
    rule = str(row.get("id") or "routing_finding")
    severity = str(row.get("severity") or "info")
    return Finding(
        id=rule,
        rule_id=f"routing.{rule}",
        title=str(row.get("title") or rule.replace("_", " ").title()),
        severity=severity,
        risk_score=risk_from_severities((severity,)),
        confidence_score=confidence_score,
        evidence_mode="static_snapshot",
        entities=_routing_entities(row),
        evidence=(
            {
                "detail": row.get("detail"),
                "count": row.get("count"),
                "items": list(row.get("items") or []),
            },
        ),
        limitations=("Static routing metadata does not prove audible signal flow.",),
        metadata={"legacy_finding_index": index, "legacy_finding": row},
    )


def _routing_entities(row: dict[str, Any]) -> tuple[EntityRef, ...]:
    entities: list[EntityRef] = []
    for item in row.get("items") or []:
        if not isinstance(item, dict):
            continue
        channel = _as_int(item.get("channel"))
        if channel is not None:
            entities.append(
                EntityRef(
                    "channel",
                    channel_entity_id(channel),
                    str(item.get("name") or f"Channel {channel}"),
                )
            )
        mixer_track = _as_int(item.get("mixer_track", item.get("target_mixer_track")))
        if mixer_track is None:
            mixer_track = _as_int(item.get("track"))
        if mixer_track is not None:
            label = str(
                item.get("mixer_name")
                or item.get("target_name")
                or f"Insert {mixer_track}"
            )
            entities.append(EntityRef("mixer_track", mixer_entity_id(mixer_track), label))
    return tuple(_dedupe_entities(entities))


def _dedupe_entities(entities: list[EntityRef]) -> list[EntityRef]:
    out = []
    seen = set()
    for entity in entities:
        key = (entity.type, entity.canonical_id)
        if key in seen:
            continue
        seen.add(key)
        out.append(entity)
    return out


def _as_int(value: Any) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return None
    return None

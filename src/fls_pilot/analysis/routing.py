"""Routing analysis report helpers."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from .canonical import channel_entity_id, mixer_entity_id
from .schema import (
    AnalysisReport,
    Coverage,
    EntityRef,
    Finding,
    Freshness,
    Prerequisite,
    pending_human_validation_ids,
    provisional_score_metadata,
)
from .scoring import clamp_score, confidence_from_coverage, risk_from_severities

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
    report_analysis_mode = _routing_analysis_mode(payload)
    finding_evidence_mode = report_analysis_mode
    coverage = _routing_coverage(ok=ok, payload=payload, details=details)
    confidence = confidence_from_coverage(
        required=coverage.required,
        available=coverage.available,
        evidence_mode=report_analysis_mode,
    )
    risk = _routing_risk_score(findings)
    analysis_findings = tuple(
        _routing_finding(
            row,
            index=index,
            confidence_score=confidence,
            evidence_mode=str(row.get("evidence_mode") or finding_evidence_mode),
        )
        for index, row in enumerate(findings, start=1)
    )
    interaction_requests = tuple(
        dict(row) for row in payload.get("interaction_requests") or () if isinstance(row, dict)
    )
    user_decisions = tuple(
        dict(row) for row in payload.get("user_decisions") or () if isinstance(row, dict)
    )
    pending_validation = pending_human_validation_ids(
        analysis_findings,
        user_decisions,
    )
    decided = {
        decision_id
        for row in user_decisions
        for decision_id in (
            str(row.get("interaction_request_id") or "").strip(),
            str(row.get("interaction_id") or "").strip(),
            str(row.get("id") or "").strip(),
        )
        if decision_id and _decision_satisfies_validation(row)
    }
    for request in interaction_requests:
        request_id = str(request.get("id") or "").strip()
        if request_id and request_id not in decided and request_id not in pending_validation:
            pending_validation = (*pending_validation, request_id)
    report_created_at, valid_until = _validity_window(created_at or payload.get("generated_at"))
    source_observations = tuple(details.get("source_observation_ids") or ())
    metadata = {
        "routing_summary": summary,
        "policy_notes": list(details.get("policy_notes") or ROUTING_POLICY_NOTES),
        "template_context": details.get("template_context") or payload.get("template_context"),
        "routing_check_level": payload.get("routing_check_level"),
        "routing_evidence_mode": payload.get("evidence_mode"),
        "routing_evidence_level": payload.get("routing_evidence_level"),
        "routing_evidence_levels": payload.get("routing_evidence_levels"),
        "template_compliance_summary": payload.get("template_compliance_summary"),
        "plan_gating_status": payload.get("plan_gating_status"),
        "cleanup_plan_allowed": payload.get("cleanup_plan_allowed"),
        "cleanup_plan_block_reason": payload.get("cleanup_plan_block_reason"),
        "required_user_decisions": payload.get("required_user_decisions"),
    }
    metadata.update(dict(payload.get("metadata") or {}))
    metadata.update(provisional_score_metadata(pending_validation))
    return AnalysisReport(
        workflow=workflow,
        title=title,
        analysis_mode=report_analysis_mode,
        evidence_mode=str(payload.get("evidence_mode") or "static_snapshot_only"),
        created_at=report_created_at,
        project_fingerprint=details.get("project_fingerprint"),
        freshness=Freshness(
            status="fresh" if ok and coverage.status == "fresh" else coverage.status,
            created_at=report_created_at,
            valid_until=valid_until,
            source_observation_ids=source_observations,
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
            Prerequisite(
                "live_meter_window",
                (
                    "ok"
                    if payload.get("playback_used") and payload.get("routing_check_level") == 2
                    else "skipped"
                    if payload.get("routing_check_level") != 2
                    else "missing"
                ),
            ),
        ),
        risk_score=risk,
        confidence_score=confidence,
        findings=analysis_findings,
        assumptions=("Channel Rack to mixer relationships are inferred from target mixer tracks.",),
        limitations=(
            "Routing review is static metadata evidence; it does not prove audible signal flow.",
            "Plugin insertion, external inputs, and UI drag-and-drop routing remain manual.",
            *tuple(str(item) for item in payload.get("limitations") or ()),
        ),
        source_observations=source_observations,
        next_actions=(
            {
                "type": "workflow",
                "id": "routing_cleanup_plan",
                "label": "Plan cleanup only after confirming routing findings and intent.",
            },
        ),
        interaction_requests=interaction_requests,
        user_decisions=user_decisions,
        safety={"read_only": True, "project_changes": False},
        metadata=metadata,
    )


def _validity_window(value: Any, *, ttl_seconds: float = 120.0) -> tuple[str, str]:
    try:
        created = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        created = datetime.now(timezone.utc)
    if created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)
    created = created.astimezone(timezone.utc)
    return created.isoformat(), (created + timedelta(seconds=ttl_seconds)).isoformat()


def _routing_analysis_mode(payload: dict[str, Any]) -> str:
    mode = str(payload.get("analysis_mode") or "").strip()
    if mode in {
        "static_snapshot",
        "live_runtime",
        "watch_window",
        "rendered_audio",
        "manual_check",
        "hybrid",
    }:
        return mode
    if payload.get("routing_check_level") == 2:
        return "hybrid"
    return "static_snapshot"


def _decision_satisfies_validation(row: dict[str, Any]) -> bool:
    if bool(row.get("skipped")):
        return False
    decision = str(row.get("decision") or "").strip().lower()
    if decision in {"skip", "skipped"}:
        return False
    if decision in {"confirm", "confirmed", "complete", "completed", "selected"}:
        return True
    if row.get("confirmed") is True or row.get("completed") is True:
        return True
    return any(key in row for key in ("selected", "selected_values", "selected_value"))


def _routing_coverage(
    *,
    ok: bool,
    payload: dict[str, Any],
    details: dict[str, Any],
) -> Coverage:
    requires_live = payload.get("routing_check_level") == 2
    required = 4 if requires_live else 3
    if not ok:
        missing = ["fl_session_alive", "channel_routing_snapshot", "routing_snapshot"]
        if requires_live:
            missing.append("live_meter_window")
        return Coverage(
            required=required,
            available=0,
            missing=tuple(missing),
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
    if requires_live:
        if payload.get("playback_used") and not payload.get("limitations"):
            available += 1
        else:
            missing.append("live_meter_window")
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
    evidence_mode: str = "static_snapshot",
) -> Finding:
    rule = str(row.get("id") or "routing_finding")
    severity = str(row.get("severity") or "info")
    row_metadata = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
    risk_score = _as_int(row.get("risk_contribution"))
    if risk_score is None:
        risk_score = risk_from_severities((severity,))
    return Finding(
        id=rule,
        rule_id=f"routing.{rule}",
        title=str(row.get("title") or rule.replace("_", " ").title()),
        severity=severity,
        risk_score=risk_score,
        confidence_score=confidence_score,
        evidence_mode=evidence_mode,
        entities=_routing_entities(row),
        evidence=(
            {
                "detail": row.get("detail"),
                "count": row.get("count"),
                "items": list(row.get("items") or []),
            },
        ),
        limitations=_routing_finding_limitations(row, evidence_mode=evidence_mode),
        metadata={
            **dict(row_metadata),
            "legacy_finding_index": index,
            "legacy_finding": row,
        },
    )


def _routing_risk_score(findings: list[dict[str, Any]]) -> int:
    explicit = [
        value
        for row in findings
        if (value := _as_int(row.get("risk_contribution"))) is not None
    ]
    if explicit:
        return clamp_score(sum(explicit))
    return risk_from_severities(tuple(row.get("severity", "info") for row in findings))


def _routing_finding_limitations(
    row: dict[str, Any],
    *,
    evidence_mode: str,
) -> tuple[str, ...]:
    explicit = row.get("limitations")
    values = [explicit] if isinstance(explicit, str) else [str(item) for item in explicit or ()]
    if evidence_mode != "hybrid":
        values.append("Static routing metadata does not prove audible signal flow.")
    return tuple(dict.fromkeys(item for item in values if item))


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
                item.get("mixer_name") or item.get("target_name") or f"Insert {mixer_track}"
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

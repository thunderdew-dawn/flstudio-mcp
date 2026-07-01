"""Runtime-owned execution adapters for existing analysis workflows."""

from __future__ import annotations

import threading
from typing import Any

from ..analysis import EVIDENCE_TYPE_RENDERED_AUDIO
from ..analysis.reports import analysis_report_for_control_center
from ..analysis.schema import AnalysisReport, Coverage, Finding, Freshness, Prerequisite
from ..analysis.scoring import confidence_from_coverage, risk_from_severities
from ..music.mix_review_levels import (
    RENDERED_MASTER_EXPECTED_CHECKS,
    RENDERED_STEM_EXPECTED_CHECKS,
)
from .core import RuntimeCore

EVIDENCE_LEVEL_LABELS = {
    1: "static_project_snapshot",
    2: "live_peak_watch",
    3: "rendered_master_evidence",
    4: "stem_bus_evidence",
}

LEGACY_AUDIO_EVIDENCE_LEVEL_LABELS = {
    1: "static_project_snapshot",
    2: "rendered_master_audio",
    3: "rendered_master_and_stems",
    4: "stem_bus_evidence",
}


class _WorkflowState:
    def __init__(self, runtime: RuntimeCore) -> None:
        self.lock = threading.RLock()
        self.broker = _RuntimeBrokerFacade(runtime)
        self.report_store = runtime


class _RuntimeBrokerFacade:
    def __init__(self, runtime: RuntimeCore) -> None:
        self._runtime = runtime

    def get_static_project_snapshot(self, bridge, policy=None):  # noqa: ANN001, ANN201
        return self._runtime.get_static_project_snapshot(bridge, policy)

    def get_live_meter_window(self, *args, **kwargs):  # noqa: ANN002, ANN003, ANN201
        return self._runtime.analysis_broker.get_live_meter_window(*args, **kwargs)


def run_workflow(
    runtime: RuntimeCore,
    workflow_id: str,
    *,
    bridge: Any | None,
    inputs: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Execute one declared workflow inside the Runtime process."""
    from .. import control_center
    from .product_workflows import run_product_workflow

    state = _WorkflowState(runtime)
    runners = {
        "mix_review": control_center._run_mix_review,
        "routing_audit": control_center._run_routing_audit,
        "low_end_analysis": control_center._run_low_end_analysis,
        "project_organizer": control_center._run_project_organizer,
    }
    runner = runners.get(workflow_id)
    if runner is None:
        return run_product_workflow(
            runtime,
            workflow_id,
            bridge=bridge,
            inputs=inputs,
        )
    safe_inputs = _legacy_workflow_inputs(inputs, workflow_id=workflow_id)
    if safe_inputs is None:
        raise ValueError(f"{workflow_id} does not accept workflow inputs")
    payload = runner(state, bridge_override=bridge, inputs=safe_inputs)
    report = runtime.latest_report(workflow_id)
    if report is None or workflow_id not in {"mix_review", "low_end_analysis"}:
        return payload
    upgraded = _apply_audio_evidence(runtime, report, workflow_id=workflow_id)
    runtime.add_report(upgraded)
    return analysis_report_for_control_center(upgraded, payload)


def _legacy_workflow_inputs(
    inputs: dict[str, Any] | None,
    *,
    workflow_id: str = "",
) -> dict[str, Any] | None:
    payload = dict(inputs or {})
    if not payload:
        return {}
    allowed = {"user_decisions"}
    if workflow_id == "mix_review":
        allowed.update(
            {
                "level",
                "genre_profile",
                "capture",
                "loop_seconds",
                "playback_mode",
                "marker_id",
                "marker_name",
                "requested_loudest_section",
                "audio_evidence",
            }
        )
    if workflow_id == "routing_audit":
        allowed.update(
            {
                "routing_check_mode",
                "template_compliance",
                "template_compliance_mode",
                "selected_template_profile",
                "template_profile_id",
                "template_slug",
                "playback_decision",
                "marker_name",
                "loop_duration_seconds",
            }
        )
    if any(key not in allowed for key in payload):
        return None
    out = {key: value for key, value in payload.items() if key in allowed}
    user_decisions = payload.get("user_decisions")
    if user_decisions is not None:
        if not isinstance(user_decisions, (list, tuple)):
            return None
        out["user_decisions"] = [dict(row) for row in user_decisions if isinstance(row, dict)]
    return out


def _apply_audio_evidence(
    runtime: RuntimeCore,
    report: AnalysisReport,
    *,
    workflow_id: str,
) -> AnalysisReport:
    observations = runtime.rendered_audio_observations(workflow_target=workflow_id)
    master = _latest_audio_observation(observations, "rendered_master")
    stems = tuple(
        row
        for row in observations
        if (row.payload if isinstance(row.payload, dict) else {}).get("evidence_kind") == "stem"
    )
    requested_level = _requested_mix_review_level(report) if workflow_id == "mix_review" else 1
    effective_master = (
        master
        if workflow_id != "mix_review" or requested_level >= 3
        else None
    )
    effective_stems = (
        stems
        if workflow_id != "mix_review" or requested_level >= 4
        else ()
    )
    audio_available = effective_master is not None
    stem_available = bool(effective_stems)
    required = report.coverage.required + (1 if workflow_id != "mix_review" else 0)
    available = report.coverage.available
    if workflow_id != "mix_review":
        available += int(audio_available)
    elif requested_level >= 3:
        available += int(audio_available)
        if requested_level >= 4:
            available += int(stem_available)
    base_missing = tuple(
        row
        for row in report.coverage.missing
        if not (
            (row == "rendered_audio_features" and audio_available)
            or (row == "rendered_stem_features" and stem_available)
        )
    )
    missing = tuple(
        row
        for row in (
            *base_missing,
            *(
                ()
                if audio_available or (workflow_id == "mix_review" and requested_level < 3)
                else ("rendered_audio_features",)
            ),
            *(
                ()
                if workflow_id != "mix_review" or requested_level < 4 or stem_available
                else ("rendered_stem_features",)
            ),
        )
        if row
    )
    coverage = Coverage(
        required=required,
        available=available,
        missing=tuple(dict.fromkeys(missing)),
        optional_available=report.coverage.optional_available + len(effective_stems),
    )
    findings = list(report.findings)
    source_observations = list(report.source_observations)
    metadata = dict(report.metadata)
    next_actions = list(report.next_actions)
    evidence_level = requested_level if workflow_id == "mix_review" else 1
    if workflow_id != "mix_review" and master is not None:
        evidence_level = 3 if stems else 2
    if effective_master is not None:
        master_payload = dict(effective_master.payload)
        summary = dict(master_payload.get("feature_summary") or {})
        source_observations.append(effective_master.observation_id)
        if workflow_id != "mix_review":
            findings.append(_audio_finding(workflow_id, summary, effective_master.observation_id))
        metadata["rendered_audio_evidence"] = {
            "level": evidence_level,
            "level_label": _evidence_level_label(evidence_level, workflow_id=workflow_id),
            "status": "available",
            "master": master_payload,
            "stems": [
                dict(row.payload) for row in effective_stems if isinstance(row.payload, dict)
            ],
            "automatic_fl_render": False,
            "mix_review_audio_findings": workflow_id != "mix_review",
        }
    else:
        if workflow_id != "mix_review" or requested_level >= 3:
            next_actions.insert(
                0,
                {
                    "type": "audio_evidence",
                    "action": "submit",
                    "label": "Analyze a manually bounced master for stronger evidence",
                    "workflow_target": workflow_id,
                },
            )
        metadata["rendered_audio_evidence"] = {
            "level": requested_level if workflow_id == "mix_review" else 1,
            "level_label": _evidence_level_label(
                requested_level if workflow_id == "mix_review" else 1,
                workflow_id=workflow_id,
            ),
            "status": (
                "not_requested"
                if workflow_id == "mix_review" and requested_level < 3
                else "missing"
            ),
            "next_action": (
                None
                if workflow_id == "mix_review" and requested_level < 3
                else "submit_rendered_master"
            ),
            "automatic_fl_render": False,
            "mix_review_audio_findings": False,
        }
    metadata.update(
        _evidence_level_metadata(
            evidence_level,
            audio_available=audio_available,
            stem_available=stem_available,
            workflow_id=workflow_id,
        )
    )
    if workflow_id == "mix_review":
        metadata.update(
            _mix_review_audio_metadata(
                metadata,
                requested_level=evidence_level,
                master=effective_master,
                stems=effective_stems,
            )
        )

    audio_risk = risk_from_severities(
        tuple(row.severity for row in findings[len(report.findings) :])
    )
    risk_score = min(100, report.risk_score + audio_risk)
    confidence = confidence_from_coverage(
        required=coverage.required,
        available=coverage.available,
        evidence_mode="hybrid" if audio_available else report.analysis_mode,
    )
    base_prerequisites = tuple(
        prerequisite
        for prerequisite in report.prerequisites
        if not (
            (prerequisite.id == "rendered_audio_features" and audio_available)
            or (prerequisite.id == "rendered_stem_features" and stem_available)
        )
    )
    return AnalysisReport(
        **{
            **report.__dict__,
            "analysis_mode": (
                "hybrid"
                if audio_available and workflow_id != "mix_review"
                else report.analysis_mode
            ),
            "evidence_mode": (
                report.evidence_mode
                if workflow_id == "mix_review"
                else "rendered_master_and_stems"
                if stems
                else "rendered_master"
                if audio_available
                else "static_snapshot_only"
            ),
            "freshness": Freshness(
                status=(
                    report.freshness.status
                    if (
                        audio_available
                        or report.freshness.status == "unavailable"
                        or (workflow_id == "mix_review" and requested_level < 3)
                    )
                    else "partial"
                ),
                created_at=report.freshness.created_at,
                valid_until=report.freshness.valid_until,
                invalidates_on=tuple(
                    dict.fromkeys(
                        (
                            *report.freshness.invalidates_on,
                            "project_identity_change",
                            "audio_source_hash_changed",
                        )
                    )
                ),
                source_observation_ids=tuple(
                    dict.fromkeys(
                        (
                            *report.freshness.source_observation_ids,
                            *source_observations,
                        )
                    )
                ),
                details=(
                    report.freshness.details
                    if audio_available or (workflow_id == "mix_review" and requested_level < 3)
                    else "Level 1 result: rendered master evidence is missing."
                ),
            ),
            "coverage": coverage,
            "prerequisites": (
                *base_prerequisites,
                *(
                    (
                        Prerequisite(
                            "rendered_audio_features",
                            "ok" if audio_available else "missing",
                            None
                            if audio_available
                            else "Static metadata cannot support audio-backed conclusions.",
                        ),
                    )
                    if workflow_id != "mix_review" or requested_level >= 3
                    else ()
                ),
                *(
                    (
                        Prerequisite(
                            "rendered_stem_features",
                            "ok" if stem_available else "missing",
                            None
                            if stem_available
                            else "Stem/bus evidence is pending external analyzer integration.",
                        ),
                    )
                    if workflow_id == "mix_review" and requested_level >= 4
                    else ()
                ),
            ),
            "risk_score": risk_score,
            "health_score": 100 - risk_score,
            "confidence_score": confidence,
            "findings": tuple(findings),
            "source_observations": tuple(dict.fromkeys(source_observations)),
            "next_actions": tuple(next_actions),
            "metadata": metadata,
        }
    )


def _requested_mix_review_level(report: AnalysisReport) -> int:
    try:
        level = int(report.metadata.get("mix_review_level") or 1)
    except (TypeError, ValueError):
        level = 1
    return min(4, max(1, level))


def _mix_review_audio_metadata(
    metadata: dict[str, Any],
    *,
    requested_level: int,
    master: Any | None,
    stems: tuple[Any, ...],
) -> dict[str, Any]:
    current = dict(metadata.get("evidence_summary") or {})
    current.update(
        {
            "rendered_master": "available" if master is not None else "missing",
            "rendered_stems": "available" if stems else "missing",
        }
    )
    linked_stems = [
        dict(row.payload)
        for row in stems
        if isinstance(getattr(row, "payload", None), dict)
    ]
    return {
        "mix_review_level": requested_level,
        "evidence_summary": current,
        "expected_checks": [
            *(RENDERED_MASTER_EXPECTED_CHECKS if requested_level >= 3 else ()),
            *(RENDERED_STEM_EXPECTED_CHECKS if requested_level >= 4 else ()),
        ],
        "external_audio_analyzer": {
            "required_for_level_3_4": requested_level >= 3,
            "available": False,
            "status": "not_merged_yet",
        },
        "linked_rendered_master": (
            dict(master.payload)
            if master is not None and isinstance(getattr(master, "payload", None), dict)
            else None
        ),
        "linked_rendered_stems": linked_stems,
    }


def _evidence_level_metadata(
    level: int,
    *,
    audio_available: bool,
    stem_available: bool = False,
    workflow_id: str = "",
) -> dict[str, Any]:
    label = _evidence_level_label(level, workflow_id=workflow_id)
    audio_requested = workflow_id != "mix_review" or level >= 3
    return {
        "evidence_level": level,
        "evidence_level_label": label,
        "audio_evidence_status": (
            "available" if audio_available else "missing" if audio_requested else "not_requested"
        ),
        "automatic_fl_render": False,
        "requires_manual_audio_export": audio_requested and not audio_available,
        "evidence_level_4": {
            "evidence_level": 4,
            "evidence_level_label": EVIDENCE_LEVEL_LABELS[4],
            "status": "available" if stem_available else "planned",
            "requires_manual_stem_export": True,
            "automatic_fl_render": False,
        },
        "level_contract": "mix_review_levels_1_4" if workflow_id == "mix_review" else "legacy",
    }


def _evidence_level_label(level: int, *, workflow_id: str = "") -> str:
    labels = (
        EVIDENCE_LEVEL_LABELS
        if workflow_id == "mix_review"
        else LEGACY_AUDIO_EVIDENCE_LEVEL_LABELS
    )
    return labels.get(level, labels[1])


def _latest_audio_observation(observations, evidence_kind: str):  # noqa: ANN001, ANN201
    rows = [
        row
        for row in observations
        if (row.payload if isinstance(row.payload, dict) else {}).get("evidence_kind")
        == evidence_kind
    ]
    return max(rows, key=lambda row: row.created_at) if rows else None


def _audio_finding(
    workflow_id: str,
    summary: dict[str, Any],
    observation_id: str,
) -> Finding:
    if workflow_id == "low_end_analysis":
        low_ratio = summary.get("low_end_energy_ratio")
        low_stereo = summary.get("low_band_stereo_proxy")
        severity = "medium" if isinstance(low_stereo, (int, float)) and low_stereo < 0 else "info"
        return Finding(
            id="low_end.rendered_audio_proxy",
            rule_id="low_end.rendered_audio_proxy",
            title="Rendered low-end energy and stereo proxies are available",
            severity=severity,
            risk_score=risk_from_severities((severity,)),
            confidence_score=95,
            evidence_mode="rendered_audio",
            evidence=(
                {
                    "low_end_energy_ratio": low_ratio,
                    "low_band_stereo_proxy": low_stereo,
                    "proxy_notice": "Not mono-cancellation proof.",
                },
            ),
            limitations=("Low-band stereo is a correlation proxy.",),
            source_observation_ids=(observation_id,),
            metadata={"evidence_type": EVIDENCE_TYPE_RENDERED_AUDIO},
        )
    peak = summary.get("peak_dbfs")
    severity = "high" if isinstance(peak, (int, float)) and peak >= 0 else "info"
    return Finding(
        id="mix.rendered_master_features",
        rule_id="mix.rendered_master_features",
        title="Rendered master level, dynamics, balance, and stereo proxies are available",
        severity=severity,
        risk_score=risk_from_severities((severity,)),
        confidence_score=95,
        evidence_mode="rendered_audio",
        evidence=(
            {
                key: summary.get(key)
                for key in (
                    "peak_dbfs",
                    "rms_dbfs",
                    "integrated_lufs",
                    "crest_factor_db",
                    "band_energy",
                    "stereo_correlation_proxy",
                    "stereo_width_proxy",
                )
            },
        ),
        limitations=("Stereo correlation is a proxy, not mono-cancellation proof.",),
        source_observation_ids=(observation_id,),
        metadata={"evidence_type": EVIDENCE_TYPE_RENDERED_AUDIO},
    )

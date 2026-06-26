"""Runtime-owned execution adapters for existing analysis workflows."""

from __future__ import annotations

import threading
from typing import Any

from ..analysis import EVIDENCE_TYPE_RENDERED_AUDIO
from ..analysis.reports import analysis_report_for_control_center
from ..analysis.schema import AnalysisReport, Coverage, Finding, Freshness, Prerequisite
from ..analysis.scoring import confidence_from_coverage, risk_from_severities
from .core import RuntimeCore

EVIDENCE_LEVEL_LABELS = {
    1: "static_project_snapshot",
    2: "rendered_master_audio",
    3: "rendered_master_and_stems",
    4: "full_song_all_channels",
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
    safe_inputs = _legacy_workflow_inputs(inputs)
    if safe_inputs is None:
        raise ValueError(f"{workflow_id} does not accept workflow inputs")
    payload = runner(state, bridge_override=bridge, inputs=safe_inputs)
    report = runtime.latest_report(workflow_id)
    if report is None or workflow_id not in {"mix_review", "low_end_analysis"}:
        return payload
    upgraded = _apply_audio_evidence(runtime, report, workflow_id=workflow_id)
    runtime.add_report(upgraded)
    return analysis_report_for_control_center(upgraded, payload)


def _legacy_workflow_inputs(inputs: dict[str, Any] | None) -> dict[str, Any] | None:
    payload = dict(inputs or {})
    if not payload:
        return {}
    allowed = {"user_decisions"}
    if any(key not in allowed for key in payload):
        return None
    user_decisions = payload.get("user_decisions")
    if not isinstance(user_decisions, (list, tuple)):
        return None
    return {"user_decisions": [dict(row) for row in user_decisions if isinstance(row, dict)]}


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
        if (row.payload if isinstance(row.payload, dict) else {}).get("evidence_kind")
        == "stem"
    )
    audio_available = master is not None
    required = report.coverage.required + 1
    available = report.coverage.available + int(audio_available)
    missing = tuple(
        row
        for row in (
            *report.coverage.missing,
            *(() if audio_available else ("rendered_audio_features",)),
        )
        if row
    )
    coverage = Coverage(
        required=required,
        available=available,
        missing=tuple(dict.fromkeys(missing)),
        optional_available=report.coverage.optional_available + len(stems),
    )
    findings = list(report.findings)
    source_observations = list(report.source_observations)
    metadata = dict(report.metadata)
    next_actions = list(report.next_actions)
    evidence_level = 1
    if master is not None:
        evidence_level = 3 if stems else 2
        master_payload = dict(master.payload)
        summary = dict(master_payload.get("feature_summary") or {})
        source_observations.append(master.observation_id)
        findings.append(_audio_finding(workflow_id, summary, master.observation_id))
        metadata["rendered_audio_evidence"] = {
            "level": evidence_level,
            "level_label": EVIDENCE_LEVEL_LABELS[evidence_level],
            "status": "available",
            "master": master_payload,
            "stems": [
                dict(row.payload) for row in stems if isinstance(row.payload, dict)
            ],
            "automatic_fl_render": False,
        }
    else:
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
            "level": 1,
            "level_label": EVIDENCE_LEVEL_LABELS[1],
            "status": "missing",
            "next_action": "submit_rendered_master",
            "automatic_fl_render": False,
        }
    metadata.update(_evidence_level_metadata(evidence_level, audio_available=audio_available))

    audio_risk = risk_from_severities(
        tuple(row.severity for row in findings[len(report.findings) :])
    )
    risk_score = min(100, report.risk_score + audio_risk)
    confidence = confidence_from_coverage(
        required=coverage.required,
        available=coverage.available,
        evidence_mode="hybrid" if audio_available else report.analysis_mode,
    )
    return AnalysisReport(
        **{
            **report.__dict__,
            "analysis_mode": "hybrid" if audio_available else report.analysis_mode,
            "evidence_mode": (
                "rendered_master_and_stems"
                if stems
                else "rendered_master"
                if audio_available
                else "static_snapshot_only"
            ),
            "freshness": Freshness(
                status=(
                    report.freshness.status
                    if audio_available or report.freshness.status == "unavailable"
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
                    if audio_available
                    else "Level 1 result: rendered master evidence is missing."
                ),
            ),
            "coverage": coverage,
            "prerequisites": (
                *report.prerequisites,
                Prerequisite(
                    "rendered_audio_features",
                    "ok" if audio_available else "missing",
                    None
                    if audio_available
                    else "Static metadata cannot support audio-backed conclusions.",
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


def _evidence_level_metadata(level: int, *, audio_available: bool) -> dict[str, Any]:
    label = EVIDENCE_LEVEL_LABELS[level]
    return {
        "evidence_level": level,
        "evidence_level_label": label,
        "audio_evidence_status": "available" if audio_available else "missing",
        "automatic_fl_render": False,
        "requires_manual_audio_export": not audio_available,
        "evidence_level_4": {
            "evidence_level": 4,
            "evidence_level_label": EVIDENCE_LEVEL_LABELS[4],
            "status": "planned",
            "requires_manual_stem_export": True,
            "automatic_fl_render": False,
        },
    }


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

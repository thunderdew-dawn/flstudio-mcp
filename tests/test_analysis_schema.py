from __future__ import annotations

import pytest

from fls_pilot.analysis import (
    ANALYSIS_REPORT_CONTRACT_VERSION,
    AnalysisReport,
    Coverage,
    EntityRef,
    Finding,
    Freshness,
    Prerequisite,
    WorkflowRequirementSet,
    requirement,
)


def test_analysis_report_contract_fields_are_explicit() -> None:
    finding = Finding(
        id="mix_peak_risk_master",
        rule_id="mix.peak.master_boundary",
        title="Master peak risk",
        severity="high",
        risk_score=68,
        confidence_score=80,
        evidence_mode="watch_window",
        entities=(EntityRef("mixer_track", "mixer:master", "Master"),),
        evidence=({"metric": "peak_dbfs", "value": 0.2, "unit": "dBFS"},),
        assumptions=("Watch capture covered the loud section.",),
        limitations=("No rendered audio spectrum was analyzed.",),
        source_observation_ids=("obs_live_meter_1",),
        recommended_next_action={"type": "workflow", "id": "gain_stage_review"},
    )
    report = AnalysisReport(
        report_id="rep_test_mix",
        workflow="mix_review",
        title="Mix Review",
        analysis_mode="hybrid",
        created_at="2026-06-16T12:00:00+00:00",
        project_fingerprint=None,
        freshness=Freshness(
            status="partial",
            created_at="2026-06-16T12:00:00+00:00",
            invalidates_on=("fl_disconnect", "project_structure_change"),
            source_observation_ids=("obs_static_1", "obs_live_meter_1"),
        ),
        coverage=Coverage(required=3, available=2, missing=("rendered_audio_features",)),
        prerequisites=(
            Prerequisite("fl_session_alive", "ok"),
            Prerequisite("rendered_audio_features", "missing"),
        ),
        risk_score=68,
        confidence_score=80,
        findings=(finding,),
        assumptions=("Low-end roles may use name heuristics.",),
        limitations=("Rendered stems were not provided.",),
        manual_checks=({"topic": "mono_sum", "check": "Check mono compatibility."},),
        source_observations=("obs_static_1", "obs_live_meter_1"),
        next_actions=({"type": "workflow", "id": "rendered_audio_analysis"},),
        safety={"read_only": True, "requires_explicit_approval": False},
    )

    data = report.to_dict()

    assert data["contract_version"] == ANALYSIS_REPORT_CONTRACT_VERSION
    assert data["report_id"] == "rep_test_mix"
    assert data["project_fingerprint"] == "unknown"
    assert data["analysis_mode"] == "hybrid"
    assert data["freshness"]["status"] == "partial"
    assert data["coverage"]["status"] == "partial"
    assert data["coverage"]["score"] == 67
    assert data["risk_score"] == 68
    assert data["risk_band"] == "high"
    assert data["health_score"] == 32
    assert data["confidence_score"] == 80
    assert data["prerequisites"][1]["status"] == "missing"
    assert data["findings"][0]["evidence_mode"] == "watch_window"
    assert data["findings"][0]["entities"][0]["canonical_id"] == "mixer:master"
    assert data["findings"][0]["source_observation_ids"] == ["obs_live_meter_1"]
    assert data["manual_checks"][0]["topic"] == "mono_sum"
    assert data["safety"]["read_only"] is True


def test_analysis_report_rejects_unknown_modes() -> None:
    with pytest.raises(ValueError, match="analysis mode"):
        AnalysisReport(workflow="x", title="X", analysis_mode="private_mode")

    with pytest.raises(ValueError, match="evidence mode"):
        Finding(
            id="finding",
            rule_id="rule",
            title="Finding",
            severity="info",
            risk_score=10,
            confidence_score=10,
            evidence_mode="private_mode",
        )


def test_analysis_report_pack_metadata_round_trips_without_new_envelope() -> None:
    report = AnalysisReport(
        report_id="rep_pack_metadata",
        workflow="low_end_analysis",
        title="Low-End Safety Check",
        analysis_mode="static_snapshot",
        pack_id="genre.low-end",
        pack_version="1.2.0",
        ruleset_id="low-end.house",
        ruleset_version="2.0.1",
        profile_id="house",
        interaction_requests=(
            {
                "id": "low_end.confirm_tracks",
                "type": "multi_select",
                "prompt": "Choose low-end tracks.",
            },
        ),
        user_decisions=(
            {
                "interaction_id": "low_end.confirm_tracks",
                "selected": ["mixer:4"],
            },
        ),
    )

    data = report.to_dict()
    restored = AnalysisReport.from_dict(data)

    assert data["contract_version"] == ANALYSIS_REPORT_CONTRACT_VERSION
    assert "report" not in data
    assert data["pack_id"] == "genre.low-end"
    assert data["pack_version"] == "1.2.0"
    assert data["ruleset_id"] == "low-end.house"
    assert data["ruleset_version"] == "2.0.1"
    assert data["profile_id"] == "house"
    assert data["interaction_requests"][0]["type"] == "multi_select"
    assert data["user_decisions"][0]["selected"] == ["mixer:4"]
    assert restored.pack_id == report.pack_id
    assert restored.pack_version == report.pack_version
    assert restored.ruleset_id == report.ruleset_id
    assert restored.ruleset_version == report.ruleset_version
    assert restored.profile_id == report.profile_id
    assert restored.interaction_requests == report.interaction_requests
    assert restored.user_decisions == report.user_decisions


def test_analysis_report_without_pack_metadata_still_loads() -> None:
    payload = AnalysisReport(
        workflow="mix_review",
        title="Mix Review",
        analysis_mode="static_snapshot",
    ).to_dict()
    for key in (
        "pack_id",
        "pack_version",
        "ruleset_id",
        "ruleset_version",
        "profile_id",
        "interaction_requests",
        "user_decisions",
    ):
        payload.pop(key)

    restored = AnalysisReport.from_dict(payload)

    assert restored.pack_id is None
    assert restored.pack_version is None
    assert restored.ruleset_id is None
    assert restored.ruleset_version is None
    assert restored.profile_id is None
    assert restored.interaction_requests == ()
    assert restored.user_decisions == ()


def test_workflow_requirement_set_separates_required_and_optional() -> None:
    requirements = WorkflowRequirementSet(
        workflow_id="low_end_analysis",
        requirements=(
            requirement("fl_session_alive", ttl_seconds=2),
            requirement("static_project_snapshot", ttl_seconds=60),
            requirement(
                "rendered_audio_features",
                required=False,
                evidence_mode="rendered_audio",
                invalidates_on=("audio_file_hash_changed",),
            ),
        ),
    )

    data = requirements.to_dict()

    assert requirements.observation_kinds(include_optional=False) == (
        "fl_session_alive",
        "static_project_snapshot",
    )
    assert data["workflow_id"] == "low_end_analysis"
    assert len(data["required"]) == 2
    assert data["optional"][0]["observation_kind"] == "rendered_audio_features"
    assert data["optional"][0]["evidence_mode"] == "rendered_audio"

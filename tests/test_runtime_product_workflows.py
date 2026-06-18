from __future__ import annotations

from pathlib import Path

import numpy as np
import soundfile as sf

from fls_pilot import protocol
from fls_pilot.analysis.schema import AnalysisReport
from fls_pilot.runtime.core import RuntimeCore
from fls_pilot.runtime.product_workflows import build_audio_evidence_report
from fls_pilot.runtime.workflow_runner import run_workflow

from test_runtime_core import FakeBridge


class ProductBridge(FakeBridge):
    def call(self, command: str, params=None):  # noqa: ANN001, ANN201
        if command == protocol.CMD_PLUGIN_LIST:
            return {
                "ok": True,
                "slots": [
                    {"slot": 0, "name": "Fruity Parametric EQ 2"},
                    {"slot": 1, "name": "Fruity Limiter"},
                ],
            }
        return super().call(command, params)


def test_preflight_is_static_and_exposes_missing_level_evidence() -> None:
    runtime = RuntimeCore()
    bridge = ProductBridge()

    result = run_workflow(runtime, "preflight", bridge=bridge)

    assert result["workflow"] == "preflight"
    assert result["analysis_mode"] == "static_snapshot"
    assert "live_meter_window" in result["coverage"]["missing"]
    assert any("render" in row.lower() for row in result["limitations"])
    assert runtime.latest_report("preflight") is not None


def test_jam_structure_is_proposal_only_and_non_destructive() -> None:
    runtime = RuntimeCore()
    result = run_workflow(runtime, "jam_2_project", bridge=ProductBridge())

    assert result["workflow"] == "jam_2_project"
    assert result["metadata"]["mode"] == "planning_and_proposals_only"
    assert result["applied_changes"] == []
    assert any("Playlist clips" in row for row in result["limitations"])
    assert all(row["requires_explicit_approval"] for row in result["proposed_changes"])


def test_sidechain_check_separates_routing_facts_from_plugin_checks() -> None:
    runtime = RuntimeCore()
    bridge = ProductBridge()
    bridge.call = _sidechain_call(bridge.call)

    result = run_workflow(runtime, "sidechain_routing_check", bridge=bridge)

    assert result["metadata"]["sidechain_routes"] == 1
    assert result["manual_checks"][0]["id"] == "sidechain.verify_receiver"
    assert any("does not prove" in row for row in result["assumptions"])


def test_plugin_assistant_requires_a_target_and_inspects_one_track() -> None:
    runtime = RuntimeCore()
    missing = run_workflow(runtime, "plugin_assistant", bridge=ProductBridge())
    inspected = run_workflow(
        runtime,
        "plugin_assistant",
        bridge=ProductBridge(),
        inputs={"track": 1},
    )

    assert missing["freshness"]["status"] == "partial"
    assert "mixer_track_target" in missing["coverage"]["missing"]
    assert len(inspected["metadata"]["slots"]) == 2
    assert any("already-loaded" in row for row in inspected["limitations"])


def test_preset_assistant_keeps_loading_manual(monkeypatch) -> None:
    monkeypatch.setattr(
        "fls_pilot.runtime.product_workflows.preset_library.list_presets",
        lambda plugin_filter=None: {
            "found": True,
            "count": 2,
            "presets": {"Plugin presets": ["BA Deep", "LD Bright"]},
        },
    )
    runtime = RuntimeCore()

    result = run_workflow(
        runtime,
        "preset_assistant",
        bridge=None,
        inputs={"plugin": "Serum", "description": "bright lead"},
    )

    assert result["workflow"] == "preset_assistant"
    assert result["metadata"]["plugin"] == "Serum"
    assert any("loading is manual" in row for row in result["limitations"])


def test_audio_evidence_is_hash_scoped_and_short_stems_are_bounded(tmp_path: Path) -> None:
    path = tmp_path / "candidate.wav"
    sf.write(path, np.zeros(22050, dtype=np.float32), 22050)

    report = build_audio_evidence_report(
        str(path),
        evidence_kind="candidate",
        workflow_links=("mix_review", "low_end_analysis"),
    )
    restored = AnalysisReport.from_dict(report.to_dict())

    assert restored.analysis_mode == "rendered_audio"
    assert restored.snapshot_id.startswith("file:")
    assert restored.metadata["file"]["sha256"]
    assert restored.metadata["workflow_links"] == ["mix_review", "low_end_analysis"]
    assert restored.metadata["level"] == "L3"


def test_health_uses_linked_audio_as_confidence_upgrade(tmp_path: Path) -> None:
    runtime = RuntimeCore()
    bridge = ProductBridge()
    for workflow in (
        "mix_review",
        "routing_audit",
        "low_end_analysis",
        "project_organizer",
    ):
        run_workflow(runtime, workflow, bridge=bridge)

    path = tmp_path / "master.wav"
    sf.write(path, np.zeros(22050, dtype=np.float32), 22050)
    runtime.add_report(
        build_audio_evidence_report(
            str(path),
            evidence_kind="rendered_master",
            workflow_links=("mix_review",),
        )
    )

    health = runtime.project_health()
    mix = next(row for row in health["sections"] if row["workflow"] == "mix_review")

    assert health["overall_health_score"] is not None
    assert health["evidence_upgrades"] == [
        {
            "workflow": "mix_review",
            "report_id": mix["audio_evidence"]["report_id"],
            "evidence_mode": "rendered_master",
        }
    ]
    assert mix["coverage"]["evidence_upgrade"] == "rendered_audio"


def _sidechain_call(base_call):
    def call(command: str, params=None):  # noqa: ANN001, ANN202
        if command == protocol.CMD_MIXER_GET_ROUTING_ALL:
            return {
                "total": 2,
                "next_start": None,
                "routing": [
                    {
                        "i": 1,
                        "name": "Kick",
                        "routes_to": [{"dst": 2, "level": 0.0}, {"dst": 0, "level": 1.0}],
                    },
                    {"i": 2, "name": "Bass", "routes_to": [{"dst": 0, "level": 1.0}]},
                ],
            }
        return base_call(command, params)

    return call

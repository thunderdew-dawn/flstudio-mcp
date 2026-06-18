from __future__ import annotations

from contextlib import suppress
from datetime import datetime, timedelta, timezone

from test_runtime_core import FakeBridge

from fls_pilot import protocol, safety
from fls_pilot.analysis import AnalysisReport, Coverage, Freshness
from fls_pilot.analysis.audio_schema import AUDIO_FEATURES_CONTRACT_VERSION
from fls_pilot.runtime.artifacts import AudioArtifactStore
from fls_pilot.runtime.core import RuntimeCore
from fls_pilot.runtime.invalidation import event_for_write


def _report(workflow: str, fingerprint: str) -> AnalysisReport:
    now = datetime.now(timezone.utc)
    return AnalysisReport(
        workflow=workflow,
        title=workflow,
        analysis_mode="static_snapshot",
        project_fingerprint=fingerprint,
        freshness=Freshness(
            status="fresh",
            created_at=now.isoformat(),
            valid_until=(now + timedelta(minutes=1)).isoformat(),
        ),
        coverage=Coverage(required=1, available=1),
    )


def test_runtime_invalidation_removes_only_current_scope_reports() -> None:
    runtime = RuntimeCore()
    bridge = FakeBridge()
    snapshot = runtime.get_static_project_snapshot(bridge)
    runtime.add_report(_report("mix_review", snapshot.project_fingerprint))

    result = runtime.invalidate("routing_change")

    assert result["reports"] == 1
    assert runtime.latest_report("mix_review") is None
    assert runtime.project_context.freshness == "stale"


def test_write_scope_maps_to_conservative_events() -> None:
    assert (
        event_for_write(scope="mixer_track:3", command=protocol.CMD_MIXER_SET_VOLUME)
        == "mixer_structure_change"
    )
    assert (
        event_for_write(scope="channel:2", command=protocol.CMD_CHANNEL_SET_NAME)
        == "channel_structure_change"
    )
    assert event_for_write(scope="piano_roll") == "project_structure_change"


def test_failed_group_validation_does_not_notify(monkeypatch) -> None:
    notifications = []
    monkeypatch.setattr(
        safety,
        "_notify_runtime",
        lambda *args, **kwargs: notifications.append((args, kwargs)),
    )

    with suppress(safety.GroupWriteError):
        safety.safe_write_group(
            FakeBridge(),
            tool="bad",
            scope="project",
            writes=[{"command": "bad"}],
        )

    assert notifications == []


def test_audio_evidence_is_incompatible_after_project_identity_changes(tmp_path) -> None:
    artifacts = AudioArtifactStore(tmp_path / "artifacts")
    runtime = RuntimeCore(
        artifact_store=artifacts,
        job_store_path=tmp_path / "jobs.sqlite3",
    )
    bridge = FakeBridge()
    runtime.get_static_project_snapshot(bridge)
    manifest = artifacts.publish(
        features={
            "contract_version": AUDIO_FEATURES_CONTRACT_VERSION,
            "summary": {"duration_seconds": 1.0},
        },
        source_sha256="e" * 64,
        source_size_bytes=10,
        source_basename="mix.wav",
        extractor_version="core-1",
        configuration_fingerprint="config-1",
    )
    try:
        runtime.attach_audio_artifact(
            manifest.artifact_id,
            evidence_kind="rendered_master",
            workflow_targets=("mix_review",),
        )
        assert runtime.rendered_audio_observations(workflow_target="mix_review")

        bridge.project_state["title"] = "Another Project"
        runtime.get_static_project_snapshot(bridge)

        assert runtime.rendered_audio_observations(workflow_target="mix_review") == ()
    finally:
        runtime.close()

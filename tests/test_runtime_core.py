from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fls_pilot import protocol
from fls_pilot.analysis import (
    AnalysisReport,
    Coverage,
    Freshness,
    StaticSnapshotPolicy,
)
from fls_pilot.runtime import RuntimeSession
from fls_pilot.runtime.core import RuntimeCore


class FakeBridge:
    def __init__(self) -> None:
        self.project_state = {
            "title": "Runtime Test",
            "channel_count": 1,
            "mixer_track_count": 2,
            "pattern_count": 1,
            "playlist_track_count": 1,
        }
        self.channels = [{"index": 0, "name": "Kick", "target_mixer_track": 1}]

    def is_alive(self) -> bool:
        return True

    def heartbeat_age(self) -> float:
        return 0.1

    def call(self, command: str, params=None):  # noqa: ANN001, ANN201
        if command == protocol.CMD_GET_PROJECT_STATE:
            return dict(self.project_state)
        rows_by_command = {
            protocol.CMD_CHANNEL_ROUTING_SUMMARY: ("channels", self.channels),
            protocol.CMD_CHANNEL_LIST: ("channels", self.channels),
            protocol.CMD_MIXER_LIST_TRACKS: (
                "tracks",
                [{"i": 0, "name": "Master"}, {"i": 1, "name": "Kick"}],
            ),
            protocol.CMD_MIXER_GET_ROUTING_ALL: (
                "routing",
                [{"i": 1, "name": "Kick", "routes_to": [{"dst": 0}]}],
            ),
            protocol.CMD_PATTERN_LIST: ("patterns", [{"index": 1, "name": "Pattern 1"}]),
            protocol.CMD_PLAYLIST_LIST_TRACKS: (
                "tracks",
                [{"index": 1, "name": "Track 1"}],
            ),
        }
        key, rows = rows_by_command[command]
        return {"total": len(rows), "next_start": None, key: rows}


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


def test_runtime_tracks_stable_scope_and_snapshot_revisions() -> None:
    runtime = RuntimeCore(session=RuntimeSession(id="runtime_test"))
    bridge = FakeBridge()

    first = runtime.get_static_project_snapshot(bridge)
    first_context = runtime.project_context
    second = runtime.get_static_project_snapshot(bridge)
    second_context = runtime.project_context

    assert first.snapshot_id == second.snapshot_id
    assert first_context.project_scope_id == second_context.project_scope_id
    assert second_context.snapshot_revision == 1

    bridge.channels[0]["name"] = "Changed Kick"
    changed = runtime.get_static_project_snapshot(
        bridge,
        policy=StaticSnapshotPolicy(force_refresh=True),
    )
    assert changed.snapshot_id != first.snapshot_id
    assert runtime.project_context.project_scope_id == first_context.project_scope_id
    assert runtime.project_context.snapshot_revision == 2


def test_runtime_scopes_reports_to_current_project() -> None:
    runtime = RuntimeCore(session=RuntimeSession(id="runtime_test"))
    bridge = FakeBridge()
    snapshot = runtime.get_static_project_snapshot(bridge)

    stored = runtime.add_report(_report("mix_review", snapshot.project_fingerprint))

    assert stored.runtime_session_id == "runtime_test"
    assert stored.project_scope_id == runtime.project_context.project_scope_id
    assert stored.snapshot_id == snapshot.snapshot_id
    assert runtime.latest_report("mix_review") == stored

    bridge.project_state["title"] = "Other Project"
    runtime.get_static_project_snapshot(bridge)
    assert runtime.latest_report("mix_review") is None


def test_runtime_health_cannot_use_other_project_reports() -> None:
    runtime = RuntimeCore(session=RuntimeSession(id="runtime_test"))
    bridge = FakeBridge()
    snapshot = runtime.get_static_project_snapshot(bridge)
    runtime.add_report(_report("mix_review", snapshot.project_fingerprint))

    bridge.project_state["title"] = "Other Project"
    runtime.get_static_project_snapshot(bridge)
    health = runtime.project_health()

    assert health["project_scope_id"] == runtime.project_context.project_scope_id
    assert health["overall_health_score"] is None
    assert "mix_review" in health["missing_workflows"]

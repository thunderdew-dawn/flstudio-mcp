from __future__ import annotations

from typing import Any

from fls_pilot import protocol
from fls_pilot.analysis import AnalysisBroker, StaticSnapshotPolicy


class FakeClock:
    def __init__(self, value: float = 1000.0) -> None:
        self.value = value

    def __call__(self) -> float:
        return self.value


class FakeBridge:
    def __init__(self, *, failures: set[str] | None = None) -> None:
        self.failures = failures or set()
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.project_state = {
            "title": "Broker Test",
            "channel_count": 2,
            "mixer_track_count": 3,
            "pattern_count": 0,
            "playlist_track_count": 1,
            "playing": False,
        }
        self.pages = {
            protocol.CMD_CHANNEL_ROUTING_SUMMARY: (
                "channels",
                [
                    {"index": 0, "name": "Kick", "target_mixer_track": 1},
                    {"index": 1, "name": "Bass", "target_mixer_track": 2},
                ],
            ),
            protocol.CMD_MIXER_LIST_TRACKS: (
                "tracks",
                [
                    {"i": 0, "name": "Master"},
                    {"i": 1, "name": "Kick"},
                    {"i": 2, "name": "Bass"},
                ],
            ),
            protocol.CMD_MIXER_GET_ROUTING_ALL: (
                "routing",
                [
                    {"i": 1, "name": "Kick", "routes_to": [{"dst": 0}]},
                    {"i": 2, "name": "Bass", "routes_to": [{"dst": 0}]},
                ],
            ),
            protocol.CMD_PATTERN_LIST: ("patterns", []),
            protocol.CMD_PLAYLIST_LIST_TRACKS: ("tracks", [{"index": 1, "name": "Audio"}]),
        }

    def is_alive(self) -> bool:
        return True

    def heartbeat_age(self) -> float:
        return 0.1

    def call(self, command: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        call_params = dict(params or {})
        self.calls.append((command, call_params))
        if command in self.failures:
            raise RuntimeError(f"simulated failure for {command}")
        if command == protocol.CMD_GET_PROJECT_STATE:
            return dict(self.project_state)
        list_key, rows = self.pages[command]
        start = int(call_params.get("start") or 0)
        page = rows[start : start + 1]
        next_start = start + 1 if start + 1 < len(rows) else None
        return {"total": len(rows), "next_start": next_start, list_key: page}


def test_static_project_snapshot_collects_observations_and_canonical_counts() -> None:
    bridge = FakeBridge()
    broker = AnalysisBroker()

    snapshot = broker.get_static_project_snapshot(bridge)

    assert snapshot.observation_id
    assert snapshot.coverage.status == "fresh"
    assert snapshot.project_fingerprint.startswith("proj_")
    assert len(snapshot.channels) == 2
    assert len(snapshot.mixer_tracks) == 3
    assert snapshot.counts["patterns"]["api_count"] == 0
    assert snapshot.counts["patterns"]["display_count"] == 1
    assert snapshot.counts["playlist"]["slot_count"] == 500
    assert snapshot.template_context["matched"] is False
    assert broker.observation_store.latest("static_project_snapshot") is not None


def test_static_project_snapshot_reuses_fresh_cached_snapshot() -> None:
    bridge = FakeBridge()
    broker = AnalysisBroker()

    first = broker.get_static_project_snapshot(bridge)
    call_count = len(bridge.calls)
    second = broker.get_static_project_snapshot(bridge)

    assert len(bridge.calls) == call_count + 1
    assert bridge.calls[-1][0] == protocol.CMD_GET_PROJECT_STATE
    assert second.observation_id == first.observation_id
    assert second.project_fingerprint == first.project_fingerprint


def test_static_project_snapshot_force_refresh_repeats_bridge_reads() -> None:
    bridge = FakeBridge()
    broker = AnalysisBroker()

    first = broker.get_static_project_snapshot(bridge)
    call_count = len(bridge.calls)
    second = broker.get_static_project_snapshot(
        bridge,
        StaticSnapshotPolicy(force_refresh=True),
    )

    assert len(bridge.calls) > call_count
    assert second.observation_id != first.observation_id


def test_optional_static_read_failure_marks_partial_coverage() -> None:
    bridge = FakeBridge(failures={protocol.CMD_PLAYLIST_LIST_TRACKS})
    broker = AnalysisBroker()

    snapshot = broker.get_static_project_snapshot(bridge)

    assert snapshot.coverage.status == "partial"
    assert "playlist_tracks_snapshot" in snapshot.coverage.missing
    assert snapshot.playlist_tracks == ()
    assert any("playlist_tracks_snapshot" in error for error in snapshot.errors)


def test_static_project_snapshot_can_skip_optional_playlist_read() -> None:
    bridge = FakeBridge(failures={protocol.CMD_PLAYLIST_LIST_TRACKS})
    broker = AnalysisBroker()

    snapshot = broker.get_static_project_snapshot(
        bridge,
        StaticSnapshotPolicy(include_playlist=False),
    )

    assert snapshot.coverage.status == "fresh"
    assert "playlist_tracks_snapshot" not in snapshot.coverage.missing
    assert all(call[0] != protocol.CMD_PLAYLIST_LIST_TRACKS for call in bridge.calls)


def test_cache_refreshes_when_requested_policy_needs_more_data() -> None:
    bridge = FakeBridge()
    broker = AnalysisBroker()

    first = broker.get_static_project_snapshot(
        bridge,
        StaticSnapshotPolicy(include_patterns=False, include_playlist=False),
    )
    second = broker.get_static_project_snapshot(bridge, StaticSnapshotPolicy())

    assert second.observation_id != first.observation_id
    assert any(call[0] == protocol.CMD_PATTERN_LIST for call in bridge.calls)
    assert any(call[0] == protocol.CMD_PLAYLIST_LIST_TRACKS for call in bridge.calls)


def test_cache_refreshes_when_project_state_changes() -> None:
    bridge = FakeBridge()
    broker = AnalysisBroker()

    first = broker.get_static_project_snapshot(bridge)
    bridge.project_state["title"] = "Different Project"
    second = broker.get_static_project_snapshot(bridge)

    assert second.observation_id != first.observation_id
    assert second.project_fingerprint != first.project_fingerprint

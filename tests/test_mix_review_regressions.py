from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from fls_pilot import control_center, protocol
from fls_pilot.analysis.live import LiveMeterWindow
from fls_pilot.music import levels as levels_module
from fls_pilot.music import mix_doctor
from fls_pilot.music.levels import measure_many
from fls_pilot.tools import mix_doctor as mix_tool


class SnapshotBridge:
    def call(self, command: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        if command == protocol.CMD_PLUGIN_LIST:
            return {"slots": []}
        raise AssertionError(f"unexpected command: {command}")


class MixSnapshotBroker:
    def __init__(self, live_window: LiveMeterWindow | None = None) -> None:
        self.live_window = live_window
        self.live_window_policies: list[Any] = []

    def get_static_project_snapshot(
        self,
        _bridge: Any,
        _policy: Any | None = None,
    ) -> dict[str, Any]:
        return _playing_static_snapshot()

    def get_live_meter_window(
        self,
        _bridge: Any,
        *,
        policy: Any,
        watcher_provider: Any,
        static_snapshot: Any,
    ) -> LiveMeterWindow | None:
        self.live_window_policies.append(policy)
        return self.live_window


def _playing_static_snapshot() -> dict[str, Any]:
    return {
        "project_state": {"playing": True},
        "mixer_tracks": [
            {"i": 0, "name": "Master", "pan": 0.0, "stereo_sep": 0.0},
            {"i": 1, "name": "Lead", "pan": 0.0, "stereo_sep": 0.0},
        ],
        "routing": [{"i": 1, "routes_to": [{"dst": 0, "dst_name": "Master"}]}],
        "channels": [],
    }


def _fake_peak_measurement(
    calls: list[list[int]],
):
    def fake_measure_many(
        _bridge: Any,
        indices: list[int],
        _samples: int,
        _interval_ms: int,
    ) -> dict[int, dict[str, float | int]]:
        calls.append(list(indices))
        return {
            0: {"peak_lin": 0.25, "peak_db": -12.0, "avg_db": -18.0, "n_reads": 1},
            1: {"peak_lin": 0.50, "peak_db": -6.0, "avg_db": -12.0, "n_reads": 1},
        }

    return fake_measure_many


def test_mix_snapshot_uses_channel_names_for_default_mixer_inserts() -> None:
    snapshot = mix_doctor.gather_snapshot(
        SnapshotBridge(),
        static_snapshot={
            "project_state": {"playing": False},
            "mixer_tracks": [
                {"i": 0, "name": "Master", "pan": 0.0},
                {"i": 1, "name": "Insert 1", "pan": 0.32, "stereo_sep": 0.0},
            ],
            "routing": [{"i": 1, "routes_to": [{"dst": 0}]}],
            "channels": [
                {"channel": 0, "name": "Sub Bass", "target_mixer_track": 1},
            ],
        },
    )

    track = snapshot["tracks"][1]
    assert track["name"] == "Sub Bass"
    assert track["mixer_name"] == "Insert 1"
    assert track["channel_names"] == ["Sub Bass"]

    low_end = mix_doctor.low_end_stereo_safety(snapshot)
    assert [row["name"] for row in low_end["low_end_tracks"]] == ["Sub Bass"]
    assert "low_end_off_center" in {finding["rule"] for finding in low_end["findings"]}


def test_control_center_samples_live_meter_when_playing_with_options(monkeypatch) -> None:
    calls: list[list[int]] = []
    monkeypatch.setattr(levels_module, "measure_many", _fake_peak_measurement(calls))
    state = SimpleNamespace(broker=MixSnapshotBroker())

    snapshot = control_center._collect_mix_snapshot(state, SnapshotBridge(), options={"level": 1})

    assert calls == [[0, 1]]
    assert snapshot["levels_valid"] is True
    assert snapshot["peak_window"]["source"] == "sustained_1200ms"
    assert snapshot["tracks"][1]["peak_max"] == 0.50


def test_control_center_level_2_prefers_fresh_watch_peaks(monkeypatch) -> None:
    def fail_measure_many(*_args: Any, **_kwargs: Any) -> dict:
        raise AssertionError("fresh watch peaks should suppress inline live metering")

    monkeypatch.setattr(levels_module, "measure_many", fail_measure_many)
    live_window = LiveMeterWindow(
        target_capture_seconds=8.0,
        captured_seconds=8.0,
        read_count=10,
        watched_track_count=2,
        playback_state="playing",
        track_meter_summaries={"0": 0.25, "1": 0.75},
        freshness="fresh",
    )
    broker = MixSnapshotBroker(live_window=live_window)
    state = SimpleNamespace(broker=broker)

    snapshot = control_center._collect_mix_snapshot(
        state,
        SnapshotBridge(),
        options={"level": 2, "loop_seconds": 8},
    )

    assert broker.live_window_policies
    assert broker.live_window_policies[0].min_capture_seconds == 8.0
    assert snapshot["levels_valid"] is True
    assert snapshot["peak_window"]["source"] == "watch"
    assert snapshot["tracks"][1]["peak_max"] == 0.75


def test_mcp_mix_review_samples_live_meter_when_playing_with_options(monkeypatch) -> None:
    calls: list[list[int]] = []
    monkeypatch.setattr(levels_module, "measure_many", _fake_peak_measurement(calls))
    monkeypatch.setattr(
        mix_tool,
        "get_analysis_broker",
        lambda: MixSnapshotBroker(),
    )

    snapshot = mix_tool._gather_analysis_snapshot(
        SnapshotBridge(),
        with_params=False,
        options={"level": 1},
    )

    assert calls == [[0, 1]]
    assert snapshot["levels_valid"] is True
    assert snapshot["peak_window"]["source"] == "sustained_1200ms"


class BulkPeakBridge:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def call(self, command: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        self.calls.append(command)
        if command == protocol.CMD_MIXER_GET_ALL_PEAKS:
            tracks = list((params or {}).get("tracks") or [])
            peaks = [500000 if track == 1 else 250000 for track in tracks]
            return {"tracks": tracks, "peaks": peaks, "scale": 1000000}
        raise AssertionError(f"unexpected command: {command}")


def test_measure_many_reads_live_peaks_with_bulk_meter_command() -> None:
    bridge = BulkPeakBridge()

    measured = measure_many(bridge, [1, 2], samples=2, interval_ms=0)

    assert measured[1]["peak_lin"] == 0.5
    assert measured[2]["peak_lin"] == 0.25
    assert measured[1]["peak_db"] is not None
    assert bridge.calls == [
        protocol.CMD_MIXER_GET_ALL_PEAKS,
        protocol.CMD_MIXER_GET_ALL_PEAKS,
    ]

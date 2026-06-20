from __future__ import annotations

from typing import Any

from fls_pilot import protocol
from fls_pilot.music import mix_doctor
from fls_pilot.music.levels import measure_many


class SnapshotBridge:
    def call(self, command: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        if command == protocol.CMD_PLUGIN_LIST:
            return {"slots": []}
        raise AssertionError(f"unexpected command: {command}")


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

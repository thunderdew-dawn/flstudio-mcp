from __future__ import annotations

from fls_pilot import protocol, safety
from fls_pilot.connection import fetch_step_pages
from fls_pilot.step_sequencer import safe_set_steps


class StepBridge:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []
        self.grid = [step % 2 == 0 for step in range(64)]

    def call(self, command, params=None):
        params = dict(params or {})
        self.calls.append((command, params))
        if command == protocol.CMD_CHANNEL_GET_STEPS:
            start = int(params.get("start", 0))
            count = min(int(params.get("count", 16)), 64 - start)
            include = params.get("include") or [
                "grid",
                "vel",
                "pan",
                "shift",
                "rep",
                "release",
                "mod",
                "pitch",
            ]
            result = {
                "channel": params["channel"],
                "pattern": params.get("pattern", 1),
                "total": 64,
                "start": start,
                "count": count,
                "next_start": start + count if start + count < 64 else None,
                "capabilities": {"release": True, "mod": True, "pitch": True},
            }
            values = {
                "grid": self.grid[start : start + count],
                "vel": [0.8] * count,
                "pan": [0.0] * count,
                "shift": [0.0] * count,
                "rep": [0] * count,
                "release": [0.5] * count,
                "mod": [0.25] * count,
                "pitch": [0] * count,
            }
            result.update({field: values[field] for field in include})
            return result
        if command == protocol.CMD_CHANNEL_SET_STEPS:
            for row in params["steps"]:
                if "value" in row:
                    self.grid[int(row["step"])] = bool(row["value"])
            return {
                "channel": params["channel"],
                "pattern": params["pattern"],
                "changed": len(params["steps"]),
                "failures": [],
            }
        raise AssertionError(command)


def test_fetch_step_pages_merges_parallel_arrays() -> None:
    bridge = StepBridge()

    result = fetch_step_pages(bridge, 2, pattern=1, steps=64, page_count=16)

    assert result["count"] == 64
    assert len(result["grid"]) == 64
    assert len(result["pitch"]) == 64
    reads = [call for call in bridge.calls if call[0] == protocol.CMD_CHANNEL_GET_STEPS]
    assert len(reads) == 4


def test_partial_step_snapshot_preserves_absolute_start() -> None:
    bridge = StepBridge()

    result = safety.take_snapshot(bridge, "channel_steps:2:1:10:5")

    assert result["start"] == 10
    assert result["count"] == 5
    assert result["grid"] == bridge.grid[10:15]


def test_safe_set_steps_chunks_and_rolls_back_as_one_unit(tmp_path) -> None:
    bridge = StepBridge()
    original = list(bridge.grid)
    old_log = safety._log
    safety._log = safety.ChangeLog(tmp_path / "steps.jsonl")
    try:
        rows = [{"step": step, "value": False} for step in range(64)]
        result = safe_set_steps(
            bridge,
            tool="channel_clear_grid",
            channel=0,
            pattern=1,
            steps=rows,
            rollback_unit="clear_grid",
        )

        assert result["ok"] is True
        writes = [call for call in bridge.calls if call[0] == protocol.CMD_CHANNEL_SET_STEPS]
        assert len(writes) == 13
        assert all(len(params["steps"]) <= 5 for _, params in writes)

        rolled_back = safety.rollback_last_change(bridge)
        assert rolled_back["ok"] is True
        assert bridge.grid == original
    finally:
        safety._log = old_log

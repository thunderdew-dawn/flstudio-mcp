"""Wire-safe server orchestration for Step Sequencer reads and writes."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from . import protocol, safety

STEP_TOTAL = 64
STEP_WRITE_WINDOW = 5
STEP_FIELDS = ("grid", "vel", "pan", "shift", "rep", "release", "mod", "pitch")


def restore_action(channel: int, before: Mapping[str, Any]) -> dict[str, Any]:
    """Build one bounded restore command from a paginated step snapshot."""

    start = int(before.get("start", 0))
    grid = list(before.get("grid") or [])
    rows = []
    for offset, value in enumerate(grid):
        row = {
            "step": start + offset,
            "value": bool(value),
            "velocity": before["vel"][offset],
            "pan": before["pan"][offset],
            "shift": before["shift"][offset],
            "repeat": before["rep"][offset],
        }
        for source, target in (("release", "release"), ("mod", "mod"), ("pitch", "pitch")):
            values = before.get(source) or []
            if offset < len(values) and values[offset] is not None:
                row[target] = values[offset]
        rows.append(row)
    return {
        "command": protocol.CMD_CHANNEL_SET_STEPS,
        "params": {
            "channel": int(channel),
            "pattern": int(before["pattern"]),
            "steps": rows,
        },
    }


def _merge_step_rows(steps: list[dict]) -> list[dict]:
    merged: dict[int, dict] = {}
    for source in steps:
        row = dict(source)
        index = int(row["step"])
        current = merged.setdefault(index, {"step": index})
        current.update(row)
    return [merged[index] for index in sorted(merged)]


def build_group_writes(channel: int, pattern: int, steps: list[dict]) -> list[dict]:
    """Partition writes into contiguous windows that fit below 1000 bytes."""

    windows: dict[int, list[dict]] = {}
    for row in _merge_step_rows(steps):
        index = int(row["step"])
        window_start = (index // STEP_WRITE_WINDOW) * STEP_WRITE_WINDOW
        windows.setdefault(window_start, []).append(row)

    writes = []
    for window_start in sorted(windows):
        rows = windows[window_start]
        window_count = min(STEP_WRITE_WINDOW, STEP_TOTAL - window_start)
        params = {"channel": int(channel), "pattern": int(pattern), "steps": rows}
        encoded = protocol.encode_message(
            protocol.DIR_REQUEST,
            "00000000",
            protocol.make_request(protocol.CMD_CHANNEL_SET_STEPS, params),
        )
        protocol.ensure_wire_safe(encoded)
        writes.append(
            {
                "snap_scope": (
                    f"channel_steps:{int(channel)}:{int(pattern)}:"
                    f"{window_start}:{window_count}"
                ),
                "command": protocol.CMD_CHANNEL_SET_STEPS,
                "params": params,
                "restore": lambda before, channel=channel: restore_action(channel, before),
            }
        )
    return writes


def safe_set_steps(
    bridge,
    *,
    tool: str,
    channel: int,
    pattern: int,
    steps: list[dict],
    rollback_unit: str,
) -> dict:
    """Apply Step Sequencer rows as one rollback unit using bounded SysEx writes."""

    writes = build_group_writes(channel, pattern, steps)
    if not writes:
        return {
            "ok": True,
            "changed": 0,
            "before": [],
            "after": [],
            "rollback": None,
        }
    return safety.safe_write_group(
        bridge,
        tool=tool,
        scope=f"channel_steps:{int(channel)}:{int(pattern)}",
        writes=writes,
        rollback_unit=rollback_unit,
    )

"""Canonical FL Studio entity ids and count policies."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class CanonicalEntity:
    """Stable entity reference independent of the current display name."""

    type: str
    canonical_id: str
    index: int | None = None
    display_name: str | None = None

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "type": self.type,
            "canonical_id": self.canonical_id,
        }
        if self.index is not None:
            out["index"] = self.index
        if self.display_name:
            out["display_name"] = self.display_name
        return out


def mixer_entity_id(index: int | str) -> str:
    """Return a canonical mixer id, including FL special tracks."""
    if isinstance(index, str):
        value = index.strip().lower()
        if value in {"master", "mixer:master"}:
            return "mixer:master"
        if value in {"current", "selected", "mixer:current"}:
            return "mixer:current"
        if value.startswith("mixer:"):
            return value
        index = int(value)
    if int(index) == 0:
        return "mixer:master"
    return f"mixer:{int(index)}"


def channel_entity_id(index: int) -> str:
    return f"channel:{int(index)}"


def pattern_entity_id(index: int) -> str:
    return f"pattern:{int(index)}"


def playlist_slot_entity_id(index: int) -> str:
    return f"playlist:slot:{int(index)}"


def plugin_entity_id(*, mixer_track: int | str, slot: int) -> str:
    track_id = mixer_entity_id(mixer_track).removeprefix("mixer:")
    return f"plugin:mixer:{track_id}:slot:{int(slot)}"


def pattern_count_policy(api_count: int | None) -> dict[str, Any]:
    """FL's UI still presents Pattern 1 when some APIs report zero patterns."""
    count = max(0, int(api_count or 0))
    notes = []
    if count == 0:
        notes.append("FL Studio UI still displays Pattern 1 when API count is 0.")
    return {
        "api_count": count,
        "display_count": max(1, count),
        "display_count_policy": "minimum_one_pattern",
        "notes": notes,
    }


def playlist_count_policy(
    used_tracks: int | None,
    *,
    slot_count: int = 500,
) -> dict[str, Any]:
    """Represent fixed playlist slots separately from used playlist rows."""
    return {
        "slot_count": int(slot_count),
        "used_tracks": max(0, int(used_tracks or 0)),
        "display_mode": "fixed_slots",
    }


def mixer_count_policy(
    api_slots: int | None,
    *,
    includes_master: bool = True,
    current_available: bool = True,
) -> dict[str, Any]:
    """Represent mixer API slots and GUI/user-visible count separately."""
    slots = max(0, int(api_slots or 0))
    special_tracks = []
    if current_available:
        special_tracks.append("current")
    special_tracks.append("master")
    user_track_count = slots - 1 if includes_master and slots > 0 else slots
    return {
        "api_slots": slots,
        "user_track_count": max(0, user_track_count),
        "special_tracks": special_tracks,
        "display_count_policy": "exclude_current_and_master",
    }

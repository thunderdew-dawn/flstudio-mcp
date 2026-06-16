"""Read-only FL bridge reads used by the analysis broker."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from .. import protocol
from ..connection import fetch_all_pages

STATIC_INVALIDATION_EVENTS = (
    "fl_disconnect",
    "project_structure_change",
    "mixer_structure_change",
    "channel_structure_change",
    "routing_change",
)


@dataclass(frozen=True)
class StaticReadSpec:
    kind: str
    command: str
    list_key: str
    required: bool
    ttl_seconds: float = 60.0


CHANNEL_ROUTING_SPEC = StaticReadSpec(
    kind="channel_routing_snapshot",
    command=protocol.CMD_CHANNEL_ROUTING_SUMMARY,
    list_key="channels",
    required=True,
)
MIXER_TRACKS_SPEC = StaticReadSpec(
    kind="mixer_tracks_snapshot",
    command=protocol.CMD_MIXER_LIST_TRACKS,
    list_key="tracks",
    required=True,
)
ROUTING_SPEC = StaticReadSpec(
    kind="routing_snapshot",
    command=protocol.CMD_MIXER_GET_ROUTING_ALL,
    list_key="routing",
    required=True,
)
PATTERNS_SPEC = StaticReadSpec(
    kind="patterns_snapshot",
    command=protocol.CMD_PATTERN_LIST,
    list_key="patterns",
    required=False,
)
PLAYLIST_TRACKS_SPEC = StaticReadSpec(
    kind="playlist_tracks_snapshot",
    command=protocol.CMD_PLAYLIST_LIST_TRACKS,
    list_key="tracks",
    required=False,
)


STATIC_PAGED_READS = (
    CHANNEL_ROUTING_SPEC,
    MIXER_TRACKS_SPEC,
    ROUTING_SPEC,
    PATTERNS_SPEC,
    PLAYLIST_TRACKS_SPEC,
)


def read_project_state(bridge: Any) -> dict[str, Any]:
    payload = bridge.call(protocol.CMD_GET_PROJECT_STATE)
    return dict(payload) if isinstance(payload, Mapping) else {}


def read_paged_resource(
    bridge: Any,
    spec: StaticReadSpec,
    *,
    timeout: float | None = None,
    attempts: int = 1,
) -> dict[str, Any]:
    payload = fetch_all_pages(
        bridge,
        spec.command,
        spec.list_key,
        timeout=timeout,
        attempts=attempts,
    )
    return dict(payload) if isinstance(payload, Mapping) else {}


def payload_rows(payload: Any, list_key: str) -> list[dict[str, Any]]:
    if not isinstance(payload, Mapping):
        return []
    rows = payload.get(list_key)
    if not isinstance(rows, list):
        return []
    return [dict(row) for row in rows if isinstance(row, Mapping)]


def project_fingerprint(
    project_state: Mapping[str, Any] | None,
    *,
    counts: Mapping[str, Any] | None = None,
) -> str:
    stable_state = {}
    for key in (
        "title",
        "project_title",
        "name",
        "path",
        "channel_count",
        "mixer_track_count",
        "pattern_count",
        "playlist_track_count",
        "time_sig_num",
        "time_sig_den",
        "ppq",
    ):
        if project_state and key in project_state:
            stable_state[key] = project_state[key]

    stable_counts = dict(counts or {})
    if not stable_state and not stable_counts:
        return "unknown"

    encoded = json.dumps(
        {"project_state": stable_state, "counts": stable_counts},
        sort_keys=True,
        default=str,
        separators=(",", ":"),
    ).encode("utf-8")
    return f"proj_{hashlib.sha256(encoded).hexdigest()[:16]}"

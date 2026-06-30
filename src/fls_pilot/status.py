"""Read-only local status export for FL Studio Pilot."""

from __future__ import annotations

import argparse
import contextlib
import json
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

from . import __version__, connection, protocol, safety

READ_COMMANDS = {
    protocol.CMD_GET_PROJECT_STATE,
    protocol.CMD_GET_PROJECT_METADATA,
    protocol.CMD_GET_PLAY_STATE,
    protocol.CMD_GET_SONG_POS,
    protocol.CMD_GET_TEMPO,
    protocol.CMD_LIST_PLAYLIST_MARKERS,
    protocol.CMD_CHANNEL_LIST,
    protocol.CMD_MIXER_LIST_TRACKS,
    protocol.CMD_PATTERN_LIST,
    protocol.CMD_PLAYLIST_LIST_TRACKS,
}


def collect_status(
    *,
    offline: bool = False,
    bridge_factory: Callable[[], Any] | None = None,
) -> dict[str, Any]:
    """Collect a compact read-only snapshot for the local status.

    The collector intentionally uses existing read-only bridge commands and
    safety changelog reads only. It does not register MCP tools or mutate FL
    Studio project state.
    """
    generated_at = _now_iso()
    snapshot = _base_snapshot(generated_at)
    if offline:
        snapshot["bridge"].update(
            {
                "state": "unavailable",
                "alive": False,
                "error": "Offline preview requested; FL Studio bridge was not contacted.",
            }
        )
        _finalize_snapshot(snapshot)
        return snapshot

    bridge = None
    try:
        bridge = bridge_factory() if bridge_factory is not None else connection.get_bridge()
        wait = getattr(bridge, "wait_for_heartbeat", None)
        if callable(wait):
            wait(timeout=1.0)

        heartbeat_age = _safe_call(lambda: bridge.heartbeat_age())
        alive = bool(_safe_call(lambda: bridge.is_alive(), default=False))
        heartbeat_age_ms = (
            round(float(heartbeat_age) * 1000.0)
            if isinstance(heartbeat_age, (int, float))
            else None
        )
        snapshot["bridge"].update(
            {
                "state": "live" if alive else "unavailable",
                "alive": alive,
                "heartbeat_age_ms": heartbeat_age_ms,
            }
        )

        if not alive:
            snapshot["bridge"]["error"] = "No fresh FL Studio controller heartbeat."
            _finalize_snapshot(snapshot)
            return snapshot

        _collect_live_reads(snapshot, bridge)
    except Exception as exc:
        snapshot["bridge"].update(
            {
                "state": "unavailable",
                "alive": False,
                "error": f"{type(exc).__name__}: {exc}",
            }
        )
    finally:
        if bridge is not None:
            with contextlib.suppress(Exception):
                bridge.close()

    _finalize_snapshot(snapshot)
    return snapshot


def format_human(snapshot: dict[str, Any]) -> str:
    """Return a compact CLI summary."""
    bridge = snapshot.get("bridge", {})
    project = snapshot.get("project", {})
    evidence = snapshot.get("evidence", [])
    live_count = sum(1 for item in evidence if item.get("state") == "live")
    limited_count = sum(1 for item in evidence if item.get("state") == "limited")
    unavailable_count = sum(1 for item in evidence if item.get("state") == "unavailable")

    lines = [
        "FL Studio Pilot Status",
        "======================",
        "Mode: READ-ONLY",
        f"Generated: {snapshot.get('generated_at', 'unknown')}",
        f"Bridge: {bridge.get('state', 'unknown')}",
    ]
    if bridge.get("error"):
        lines.append(f"Bridge detail: {bridge['error']}")
    if project.get("state") == "live":
        lines.append(
            "Project: "
            f"{_display_value(project.get('tempo_bpm'), suffix=' BPM')} | "
            f"{_display_value(project.get('channel_count'))} channels | "
            f"{_display_value(project.get('mixer_track_count'))} mixer tracks"
        )

    lines.append(
        f"Evidence: {live_count} live, {limited_count} limited, {unavailable_count} unavailable"
    )
    lines.append("No FL Studio project changes were made.")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Print the read-only FL Studio Pilot local status data."
    )
    parser.add_argument(
        "--format",
        choices=["human", "json"],
        default="human",
        help="CLI output format.",
    )
    parser.add_argument(
        "--offline",
        action="store_true",
        help="Render an offline preview without contacting the FL Studio bridge.",
    )
    args = parser.parse_args(argv)

    snapshot = collect_status(offline=args.offline)

    if args.format == "json":
        print(json.dumps({"snapshot": snapshot}, indent=2))
    else:
        print(format_human(snapshot))


def _base_snapshot(generated_at: str) -> dict[str, Any]:
    history = _safe_call(lambda: safety.change_history(limit=1), default={"entries": []})
    entries = history.get("entries", []) if isinstance(history, dict) else []
    return {
        "schema_version": 1,
        "app": {
            "name": "fls-pilot",
            "version": __version__,
            "target_version": "v3 beta",
        },
        "mode": "read-only",
        "generated_at": generated_at,
        "bridge": {
            "state": "unavailable",
            "alive": False,
            "heartbeat_age_ms": None,
            "fl_version": None,
        },
        "project": _empty_panel("Project Snapshot"),
        "transport": _empty_panel("Transport"),
        "resources": {
            "channels": _empty_resource("channels"),
            "mixer": _empty_resource("tracks"),
            "patterns": _empty_resource("patterns"),
            "playlist": _empty_resource("tracks"),
        },
        "safety": {
            "state": "server-state",
            "read_only": True,
            "dry_run_available": True,
            "dry_run_enabled": bool(_safe_call(safety.is_dry_run, default=False)),
            "rollback_available": bool(entries),
            "last_change": entries[-1] if entries else None,
            "note": (
                "Status reads safety state only; rollback is executed through MCP safety tools."
            ),
        },
        "analysis": {
            "mix_risk": {
                "state": "limited",
                "headline": "Audio peak/headroom risk is not measured by this status.",
                "detail": "Run Mix Review or peak watch for audio-level evidence.",
            },
            "organization": {
                "state": "unavailable",
                "signals": [],
            },
        },
        "evidence": [],
    }


def _collect_live_reads(snapshot: dict[str, Any], bridge) -> None:
    project = _safe_bridge_call(bridge, protocol.CMD_GET_PROJECT_STATE)
    if project["ok"]:
        data = project["data"]
        snapshot["project"].update(
            {
                "state": "live",
                "fl_version": data.get("fl_version"),
                "tempo_bpm": data.get("tempo_bpm"),
                "playing": data.get("playing"),
                "recording": data.get("recording"),
                "pattern_number": data.get("pattern_number"),
                "pattern_count": data.get("pattern_count"),
                "channel_count": data.get("channel_count"),
                "mixer_track_count": data.get("mixer_track_count"),
            }
        )
        snapshot["bridge"]["fl_version"] = data.get("fl_version")
    else:
        snapshot["project"].update({"state": "unavailable", "error": project["error"]})

    play_state = _safe_bridge_call(bridge, protocol.CMD_GET_PLAY_STATE)
    song_position = _safe_bridge_call(bridge, protocol.CMD_GET_SONG_POS)
    tempo = _safe_bridge_call(bridge, protocol.CMD_GET_TEMPO)
    markers = _safe_bridge_call(bridge, protocol.CMD_LIST_PLAYLIST_MARKERS)
    if play_state["ok"] or song_position["ok"] or tempo["ok"]:
        play_data = play_state.get("data") if play_state["ok"] else {}
        snapshot["transport"].update(
            {
                "state": "live",
                **(play_data if isinstance(play_data, dict) else {}),
                "song_position": song_position.get("data") if song_position["ok"] else None,
                "tempo": tempo.get("data") if tempo["ok"] else None,
                "markers": markers.get("data") if markers["ok"] else None,
            }
        )
    else:
        snapshot["transport"].update(
            {
                "state": "unavailable",
                "error": "; ".join(
                    result["error"] for result in (play_state, song_position, tempo)
                ),
            }
        )

    metadata = _safe_bridge_call(bridge, protocol.CMD_GET_PROJECT_METADATA)
    if metadata["ok"]:
        snapshot["project"]["metadata"] = metadata["data"]
    else:
        snapshot["project"]["metadata"] = {
            "state": "unavailable",
            "error": metadata["error"],
        }

    snapshot["resources"]["channels"] = _safe_fetch_resource(
        bridge, protocol.CMD_CHANNEL_LIST, "channels"
    )
    snapshot["resources"]["mixer"] = _safe_fetch_resource(
        bridge, protocol.CMD_MIXER_LIST_TRACKS, "tracks"
    )
    snapshot["resources"]["patterns"] = _safe_fetch_resource(
        bridge, protocol.CMD_PATTERN_LIST, "patterns"
    )
    snapshot["resources"]["playlist"] = _safe_fetch_resource(
        bridge, protocol.CMD_PLAYLIST_LIST_TRACKS, "tracks"
    )


def _finalize_snapshot(snapshot: dict[str, Any]) -> None:
    resources = snapshot["resources"]
    project = snapshot["project"]
    playlist = resources["playlist"]
    if playlist.get("state") == "live":
        project["playlist_track_count"] = playlist.get("total")

    snapshot["analysis"]["organization"] = _organization_signals(resources)
    snapshot["evidence"] = _evidence_feed(snapshot)


def _organization_signals(resources: dict[str, Any]) -> dict[str, Any]:
    channels = resources.get("channels", {})
    mixer = resources.get("mixer", {})
    patterns = resources.get("patterns", {})
    playlist = resources.get("playlist", {})

    signals: list[dict[str, Any]] = []
    if channels.get("state") == "live":
        channel_items = channels.get("items", [])
        duplicate_names = _duplicate_name_count(channel_items)
        muted_channels = sum(1 for item in channel_items if item.get("mute"))
        signals.extend(
            [
                {
                    "label": "Duplicate Channel Names",
                    "value": duplicate_names,
                    "state": "live",
                    "detail": "Computed from capped Channel Rack list names.",
                },
                {
                    "label": "Muted Channels",
                    "value": muted_channels,
                    "state": "live",
                    "detail": "Read from Channel Rack list state.",
                },
            ]
        )
    else:
        signals.append(
            {
                "label": "Channel Organization",
                "value": "Unavailable",
                "state": "unavailable",
                "detail": channels.get("error", "Channel list was not available."),
            }
        )

    if mixer.get("state") == "live":
        tracks = mixer.get("items", [])
        signals.extend(
            [
                {
                    "label": "Muted Mixer Inserts",
                    "value": sum(1 for item in tracks if item.get("mute")),
                    "state": "live",
                    "detail": "Read from mixer track list state.",
                },
                {
                    "label": "Soloed Mixer Inserts",
                    "value": sum(1 for item in tracks if item.get("solo")),
                    "state": "live",
                    "detail": "Read from mixer track list state.",
                },
            ]
        )

    if playlist.get("state") == "live":
        signals.append(
            {
                "label": "Playlist Tracks",
                "value": playlist.get("total", len(playlist.get("items", []))),
                "state": "live",
                "detail": "Track metadata only; playlist clip edits are unsupported.",
            }
        )

    if patterns.get("state") == "live":
        pattern_items = patterns.get("items", [])
        signals.append(
            {
                "label": "Default Pattern Names",
                "value": sum(
                    1
                    for item in pattern_items
                    if str(item.get("name", "")).strip().lower().startswith("pattern")
                ),
                "state": "live",
                "detail": "Name-only signal from the pattern resource.",
            }
        )

    signals.append(
        {
            "label": "Direct-to-Master Channels",
            "value": "Limited",
            "state": "limited",
            "detail": (
                "The compact channel list omits target mixer tracks; use detail reads for this."
            ),
        }
    )
    return {"state": _aggregate_state(signals), "signals": signals}


def _evidence_feed(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    generated_at = snapshot["generated_at"]
    bridge = snapshot["bridge"]
    project = snapshot["project"]
    transport = snapshot["transport"]
    resources = snapshot["resources"]
    safety_state = snapshot["safety"]
    metadata = project.get("metadata") if isinstance(project.get("metadata"), dict) else {}
    markers = transport.get("markers") if isinstance(transport.get("markers"), dict) else {}
    items = [
        {
            "label": "Bridge heartbeat",
            "state": bridge.get("state", "unavailable"),
            "value": _display_ms(bridge.get("heartbeat_age_ms")),
            "source": "FL Studio controller",
            "timestamp": generated_at,
            "detail": bridge.get("error") or "Fresh controller heartbeat.",
        },
        {
            "label": "Project snapshot",
            "state": project.get("state", "unavailable"),
            "value": _display_value(project.get("tempo_bpm"), suffix=" BPM"),
            "source": "fl://project equivalent",
            "timestamp": generated_at,
            "detail": project.get("error") or "Tempo, transport, and project counts.",
        },
        {
            "label": "Project metadata",
            "state": metadata.get("state", "unavailable"),
            "value": _display_value(metadata.get("title")),
            "source": "general.getProjectTitle/Author/Genre",
            "timestamp": generated_at,
            "detail": (
                metadata.get("error")
                or "Title, author, and genre are read-only; metadata writes are API-limited."
            ),
        },
        {
            "label": "Playlist time markers",
            "state": markers.get("state", "unavailable"),
            "value": _display_value(markers.get("total")),
            "source": "arrangement.getMarkerName",
            "timestamp": generated_at,
            "detail": (
                markers.get("reason")
                or markers.get("position_note")
                or "Marker names are available for transient navigation."
            ),
        },
        {
            "label": "Channel summary",
            "state": resources["channels"].get("state", "unavailable"),
            "value": _resource_count(resources["channels"]),
            "source": "fl://channels equivalent",
            "timestamp": generated_at,
            "detail": resources["channels"].get("error") or "Capped Channel Rack metadata.",
        },
        {
            "label": "Mixer summary",
            "state": resources["mixer"].get("state", "unavailable"),
            "value": _resource_count(resources["mixer"]),
            "source": "fl://mixer equivalent",
            "timestamp": generated_at,
            "detail": resources["mixer"].get("error") or "Capped mixer metadata.",
        },
        {
            "label": "Playlist track metadata",
            "state": resources["playlist"].get("state", "unavailable"),
            "value": _resource_count(resources["playlist"]),
            "source": "fl://playlist track list",
            "timestamp": generated_at,
            "detail": (
                resources["playlist"].get("error") or "Track metadata; clip editing excluded."
            ),
        },
        {
            "label": "Safety changelog",
            "state": "cached" if safety_state.get("last_change") else "server-state",
            "value": "Rollback ready" if safety_state.get("rollback_available") else "No changes",
            "source": "MCP safety changelog",
            "timestamp": generated_at,
            "detail": safety_state.get("note"),
        },
        {
            "label": "Audio peak analysis",
            "state": "limited",
            "value": "Not sampled",
            "source": "Status scope",
            "timestamp": generated_at,
            "detail": "Run Mix Review or peak watch for dBFS/headroom findings.",
        },
    ]
    return items


def _safe_fetch_resource(bridge, command: str, list_key: str) -> dict[str, Any]:
    if command not in READ_COMMANDS:
        return {
            "state": "unavailable",
            "total": 0,
            "shown": 0,
            "items": [],
            "error": f"Refused non-read status command: {command}",
        }
    try:
        data = connection.fetch_all_pages(
            bridge,
            command,
            list_key,
            timeout=2.0,
            attempts=2,
        )
    except Exception as exc:
        out = _empty_resource(list_key)
        out["error"] = f"{type(exc).__name__}: {exc}"
        return out

    items = data.get(list_key) or []
    return {
        "state": "live",
        "total": data.get("total", len(items)),
        "shown": len(items),
        "items": items,
    }


def _safe_bridge_call(bridge, command: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    if command not in READ_COMMANDS:
        return {"ok": False, "error": f"Refused non-read status command: {command}"}
    try:
        return {
            "ok": True,
            "data": connection.call_with_retry(
                bridge,
                command,
                params,
                timeout=2.0,
                attempts=2,
            ),
        }
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


def _safe_call(fn, default=None):
    try:
        return fn()
    except Exception:
        return default


def _empty_panel(title: str) -> dict[str, Any]:
    return {"title": title, "state": "unavailable", "error": None}


def _empty_resource(list_key: str) -> dict[str, Any]:
    return {"state": "unavailable", "total": 0, "shown": 0, "items": [], "list_key": list_key}


def _duplicate_name_count(items: list[dict[str, Any]]) -> int:
    counts: dict[str, int] = {}
    for item in items:
        name = str(item.get("name") or "").strip().lower()
        if not name:
            continue
        counts[name] = counts.get(name, 0) + 1
    return sum(count - 1 for count in counts.values() if count > 1)


def _aggregate_state(signals: list[dict[str, Any]]) -> str:
    states = {signal.get("state") for signal in signals}
    if "live" in states:
        return "live"
    if "limited" in states:
        return "limited"
    return "unavailable"


def _resource_count(resource: dict[str, Any]) -> str:
    if resource.get("state") != "live":
        return "Unavailable"
    return f"{resource.get('shown', 0)} / {resource.get('total', 0)}"


def _display_value(value, *, suffix: str = "") -> str:
    if value is None:
        return "N/A"
    if isinstance(value, float):
        return f"{value:.3f}{suffix}"
    return f"{value}{suffix}"


def _display_ms(value) -> str:
    if value is None:
        return "N/A"
    return f"{value} ms"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


if __name__ == "__main__":
    main()

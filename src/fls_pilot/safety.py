"""Safety layer: snapshot / changelog / rollback / dry-run for write tools.

Lives on the MCP-SERVER side -- the server can do file I/O, the FL controller
script cannot. Every write tool routes through :func:`safe_write`, which
snapshots the affected scope, logs the change, executes, reads back, and
returns before+after so the caller (and a human) can see exactly what changed.
"""

from __future__ import annotations

import json
import threading
import time
import uuid
from collections import deque
from collections.abc import Mapping
from pathlib import Path

from .protocol import (
    CMD_CHANNEL_GET,
    CMD_CHANNEL_LIST,
    CMD_CHANNEL_SELECTED,
    CMD_GET_PROJECT_STATE,
    CMD_GET_TEMPO,
    CMD_GET_TIME_SIG,
    CMD_MIXER_GET_EQ,
    CMD_MIXER_GET_ROUTING,
    CMD_MIXER_GET_SLOT,
    CMD_MIXER_GET_TRACK,
    CMD_MIXER_GET_TRACK_SLOTS,
    CMD_MIXER_LIST_TRACKS,
    CMD_MIXER_SELECTED,
    CMD_PATTERN_GET,
    CMD_PATTERN_LIST,
    CMD_PATTERN_SELECTED,
    CMD_PLAYLIST_GET_TRACK,
    CMD_PLUGIN_GET_PARAM,
)

_DIR = Path.home() / ".fls-pilot"
_PATH = _DIR / "changelog.jsonl"
_MAX = 50
_SCHEMA_VERSION = 1


class ChangeLog:
    """Rolling deque of the last ``_MAX`` writes, persisted to a jsonl file."""

    def __init__(self, path: Path = _PATH, max_entries: int = _MAX) -> None:
        self._path = Path(path)
        self._max_entries = max_entries
        self._lock = threading.Lock()
        self._dq: deque = deque(maxlen=max_entries)
        self._load()

    def _load(self) -> None:
        try:
            if self._path.exists():
                migrated = False
                for line in self._path.read_text(encoding="utf-8").splitlines():
                    line = line.strip()
                    if line:
                        raw = json.loads(line)
                        entry = self._normalize(raw)
                        migrated = migrated or entry != raw
                        self._dq.append(entry)
                if migrated:
                    self._persist()
        except Exception:
            pass

    def _persist(self) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text("".join(json.dumps(e) + "\n" for e in self._dq), encoding="utf-8")
        except Exception:
            pass

    def _normalize(self, entry: dict) -> dict:
        out = dict(entry)
        out.setdefault("schema_version", _SCHEMA_VERSION)
        out.setdefault("change_id", _new_change_id())
        out.setdefault("ts", time.time())
        return out

    def append(self, entry: dict) -> dict:
        entry = self._normalize(entry)
        with self._lock:
            self._dq.append(entry)
            self._persist()
        return entry

    def pop_last(self):
        with self._lock:
            if not self._dq:
                return None
            entry = self._dq.pop()
            self._persist()
            return entry

    def pop_latest_matching(self, change_id: str):
        with self._lock:
            if not self._dq:
                return None, "empty"
            latest = self._dq[-1]
            if latest.get("change_id") == change_id:
                entry = self._dq.pop()
                self._persist()
                return entry, None
            for entry in self._dq:
                if entry.get("change_id") == change_id:
                    return None, "non_lifo"
            return None, "not_found"

    def recent(self, n: int = 10, *, include_payload: bool = False) -> list:
        with self._lock:
            entries = list(self._dq)[-max(0, int(n)) :]
        if include_payload:
            return entries
        return [_entry_summary(e) for e in entries]

    def path(self) -> str:
        return str(self._path)

    def export(self, output_path: str | None = None, *, include_payload: bool = True) -> dict:
        entries = self.recent(self._max_entries, include_payload=include_payload)
        data = {
            "schema_version": _SCHEMA_VERSION,
            "exported_at": time.time(),
            "count": len(entries),
            "entries": entries,
        }
        if output_path:
            out = Path(output_path).expanduser()
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(json.dumps(data, indent=2), encoding="utf-8")
            data["path"] = str(out)
        else:
            data["path"] = self.path()
            data["format"] = "jsonl"
        return data


def _new_change_id() -> str:
    return f"chg_{time.time_ns()}_{uuid.uuid4().hex[:8]}"


def _entry_summary(entry: dict) -> dict:
    out = {
        "change_id": entry.get("change_id"),
        "ts": entry.get("ts"),
        "tool": entry.get("tool"),
        "rollback_unit": entry.get("rollback_unit") or entry.get("tool"),
        "scope": entry.get("scope"),
        "group": bool(entry.get("group")),
        "command": entry.get("command"),
    }
    if entry.get("rollback_note"):
        out["rollback_note"] = entry.get("rollback_note")
    if entry.get("change_id"):
        out["undo"] = _undo_text(entry["change_id"])
    return out


_log = ChangeLog()
_dry_run = False


class GroupWriteError(RuntimeError):
    """Raised when a grouped write fails validation, snapshot, execution, or rollback."""

    def __init__(self, result: dict) -> None:
        self.result = result
        super().__init__(result.get("error") or "group write failed")


def set_dry_run(enabled) -> dict:
    global _dry_run
    _dry_run = bool(enabled)
    return {"dry_run": _dry_run}


def is_dry_run() -> bool:
    return _dry_run


def get_changelog() -> ChangeLog:
    return _log


def take_snapshot(bridge, scope):
    """Read current state for a scope so it can be restored or recorded.

    scope: "mixer_track:N" | "channel:N" | "mixer_all" | "channels_all"
           | "plugin_param:TRACK:SLOT:PARAM" | "tempo" | "selected_channel"
           | "patterns_all" | "project_state"
           | "channel_steps:CHANNEL[:PATTERN]" | "pattern:INDEX" | "patterns_selected"
           | "playlist_track:INDEX" | "mixer_eq:TRACK" | "effect_slot:TRACK:SLOT"
           | "track_slots:TRACK" | "time_signature"
    """
    kind, _, arg = str(scope).partition(":")
    if kind == "tempo":
        return bridge.call(CMD_GET_TEMPO)
    if kind == "selected_channel":
        return bridge.call(CMD_CHANNEL_SELECTED)
    if kind == "mixer_selection":
        return bridge.call(CMD_MIXER_SELECTED)
    if kind == "project_state":
        return bridge.call(CMD_GET_PROJECT_STATE)
    if kind == "patterns_all":
        from .connection import fetch_all_pages

        out = fetch_all_pages(bridge, CMD_PATTERN_LIST, "patterns")
        out["project"] = bridge.call(CMD_GET_PROJECT_STATE)
        return out
    if kind == "mixer_track":
        return bridge.call(CMD_MIXER_GET_TRACK, {"index": int(arg)})
    if kind == "channel":
        return bridge.call(CMD_CHANNEL_GET, {"index": int(arg)})
    if kind == "plugin_param":
        track, slot, idx = (int(x) for x in arg.split(":"))
        return bridge.call(CMD_PLUGIN_GET_PARAM, {"track": track, "slot": slot, "param": idx})
    if kind == "route":
        src, dst = (int(x) for x in arg.split(":"))
        info = bridge.call(CMD_MIXER_GET_ROUTING, {"track": src})
        enabled = any(d.get("dst") == dst for d in info.get("routes_to", []))
        return {"src": src, "dst": dst, "enabled": enabled}
    if kind == "mixer_all":
        from .connection import fetch_all_pages

        return fetch_all_pages(bridge, CMD_MIXER_LIST_TRACKS, "tracks")
    if kind == "channels_all":
        from .connection import fetch_all_pages

        return fetch_all_pages(bridge, CMD_CHANNEL_LIST, "channels")
    if kind == "channel_steps":
        parts = [int(x) for x in arg.split(":")]
        from .connection import fetch_step_pages

        channel = parts[0]
        pattern = parts[1] if len(parts) > 1 else None
        start = parts[2] if len(parts) > 2 else 0
        count = parts[3] if len(parts) > 3 else 64 - start
        return fetch_step_pages(
            bridge,
            channel,
            pattern=pattern,
            steps=64,
            start=start,
            read_count=count,
        )
    if kind == "pattern":
        return bridge.call(CMD_PATTERN_GET, {"index": int(arg)})
    if kind == "patterns_selected":
        return bridge.call(CMD_PATTERN_SELECTED)
    if kind == "playlist_track":
        return bridge.call(CMD_PLAYLIST_GET_TRACK, {"index": int(arg)})
    if kind == "mixer_eq":
        return bridge.call(CMD_MIXER_GET_EQ, {"track": int(arg)})
    if kind == "effect_slot":
        track, slot = (int(x) for x in arg.split(":"))
        return bridge.call(CMD_MIXER_GET_SLOT, {"track": track, "slot": slot})
    if kind == "track_slots":
        return bridge.call(CMD_MIXER_GET_TRACK_SLOTS, {"track": int(arg)})
    if kind == "time_signature":
        return bridge.call(CMD_GET_TIME_SIG)
    raise ValueError(f"unknown snapshot scope: {scope!r}")


def _dry_run_plan(tool, command, params):
    return {
        "ok": True,
        "dry_run": True,
        "planned": {"tool": tool, "command": command, "params": params},
    }


def _undo_text(change_id: str) -> str:
    return (
        f"call fl_rollback_change(change_id={change_id!r}) while it is the latest "
        "change, or fl_rollback_last_change()"
    )


def _rollback_guidance(entry: Mapping) -> dict:
    change_id = str(entry["change_id"])
    return {
        "change_id": change_id,
        "rollback_unit": entry.get("rollback_unit") or entry.get("tool"),
        "rollback_path": "MCP safety changelog",
        "undo": _undo_text(change_id),
    }


def _verify_retry(bridge, command, params, result, verify, attempts=4, delay=0.06):
    """Re-issue a toggle-style command until its reported state sticks.

    FL occasionally drops a mute/solo toggle when it lands too close to other
    writes (it coalesces these over a short window). Each re-issue is a fresh
    SysEx = a fresh FL script-tick + latency = spacing, so it lands.
    """
    if verify is None:
        return result
    field, expected = verify
    n = 0
    while result.get(field) != expected and n < attempts:
        time.sleep(delay)
        result = bridge.call(command, params)
        n += 1
    return result


def _read_scope_with_poll(bridge, scope, verify=None, attempts=5, delay=0.08):
    result = take_snapshot(bridge, scope)
    if verify is None:
        return result
    field, expected = verify
    n = 0
    while result.get(field) != expected and n < attempts:
        time.sleep(delay * (n + 1))
        result = take_snapshot(bridge, scope)
        n += 1
    return result


def _require_verified_readback(result: dict, verify, index: int) -> None:
    if verify is None:
        return
    field, expected = verify
    actual = result.get(field)
    if actual != expected:
        raise RuntimeError(
            f"write #{index} readback {field!r}={actual!r} did not match expected {expected!r}"
        )


def _validate_group_write_entry(write, index: int) -> dict:
    if not isinstance(write, Mapping):
        raise ValueError(f"write #{index} must be a mapping")
    snap_scope = write.get("snap_scope")
    if not isinstance(snap_scope, str) or not snap_scope:
        raise ValueError(f"write #{index} missing snap_scope")
    command = write.get("command")
    if not isinstance(command, str) or not command:
        raise ValueError(f"write #{index} missing command")
    params = write.get("params") or {}
    if not isinstance(params, Mapping):
        raise ValueError(f"write #{index} params must be a mapping")
    restore = write.get("restore")
    if not callable(restore):
        raise ValueError(f"write #{index} missing restore callable")
    read_scope = write.get("read_scope") or snap_scope
    if not isinstance(read_scope, str) or not read_scope:
        raise ValueError(f"write #{index} read_scope must be a string")
    verify = write.get("verify")
    if verify is not None:
        if not isinstance(verify, tuple | list) or len(verify) != 2:
            raise ValueError(f"write #{index} verify must be a (field, expected) pair")
        verify = (verify[0], verify[1])
        if not isinstance(verify[0], str) or not verify[0]:
            raise ValueError(f"write #{index} verify field must be a string")
    return {
        "index": index,
        "snap_scope": snap_scope,
        "read_scope": read_scope,
        "command": command,
        "params": dict(params),
        "restore": restore,
        "verify": verify,
    }


def _validate_group_writes(writes) -> list[dict]:
    if writes is None:
        raise ValueError("writes must be a list")
    return [_validate_group_write_entry(write, index) for index, write in enumerate(writes)]


def _validate_restore_action(restore, index: int) -> dict:
    if not isinstance(restore, Mapping):
        raise ValueError(f"restore #{index} must be a mapping")
    command = restore.get("command")
    if not isinstance(command, str) or not command:
        raise ValueError(f"restore #{index} missing command")
    params = restore.get("params") or {}
    if not isinstance(params, Mapping):
        raise ValueError(f"restore #{index} params must be a mapping")
    return {"command": command, "params": dict(params)}


def _restore_verify_from_params(result: dict, params: Mapping):
    if "state" in params:
        field = "mute" if "mute" in result else ("solo" if "solo" in result else None)
        if field is not None:
            return (field, params["state"])
    if "enabled" in params and "enabled" in result:
        return ("enabled", params["enabled"])
    return None


def _call_restore(bridge, restore: Mapping) -> dict:
    params = restore.get("params") or {}
    restored = bridge.call(restore["command"], params)
    verify = _restore_verify_from_params(restored, params)
    if verify is not None:
        restored = _verify_retry(bridge, restore["command"], params, restored, verify)
    return restored


def _rollback_executed_group_writes(bridge, executed: list[dict]) -> dict:
    results = []
    ok = True
    for item in reversed(executed):
        restore = item["restore"]
        try:
            restored = _call_restore(bridge, restore)
            results.append({"index": item["index"], "ok": True, "restored": restored})
        except Exception as exc:
            ok = False
            results.append(
                {
                    "index": item["index"],
                    "ok": False,
                    "error": f"{type(exc).__name__}: {exc}",
                    "restore": restore,
                }
            )
    return {"ok": ok, "results": results}


def _raise_group_write_error(result: dict):
    raise GroupWriteError(result)


def safe_write(
    bridge,
    *,
    tool,
    scope,
    command,
    params,
    build_restore,
    verify=None,
    rollback_unit=None,
):
    """Snapshot -> log -> execute -> (verify+retry) -> read back. Honors dry-run.

    ``build_restore(before)`` returns ``{"command", "params"}`` that undoes
    this change. ``verify=(field, expected)`` re-issues the command until the
    reported state matches (used for flaky toggle writes like mute/solo).
    """
    if _dry_run:
        return _dry_run_plan(tool, command, params)
    before = take_snapshot(bridge, scope)
    restore = build_restore(before)
    echo = bridge.call(command, params)
    echo = _verify_retry(bridge, command, params, echo, verify)
    # FL commits some writes (notably mixer fader volume/pan) on a LATER
    # script-tick, so the handler's SAME-tick readback (echo) can report the
    # stale pre-write value. Re-read the scope on a FRESH tick for the TRUE
    # post-write state. Fall back to the echo if the scope can't be re-read.
    try:
        after = _read_scope_with_poll(bridge, scope, verify=verify)
    except Exception:
        after = echo
    entry = _log.append(
        {
            "tool": tool,
            "rollback_unit": rollback_unit or tool,
            "scope": scope,
            "command": command,
            "params": params,
            "before": before,
            "after": after,
            "echo": echo,
            "restore": restore,
            "ts": time.time(),
        }
    )
    _notify_runtime(bridge, scope=scope, command=command)
    return {
        "ok": True,
        "change_id": entry["change_id"],
        "rollback": _rollback_guidance(entry),
        "undo": _undo_text(entry["change_id"]),
        "before": before,
        "after": after,
    }


def safe_piano_roll_write(bridge, *, tool, params, apply):
    """Run a generated Piano Roll script and log FL undo as the restore action.

    FL's Piano Roll scripting API can mutate notes, but the controller API
    cannot read those notes back into the MCP server. The generated scripts wrap
    their edit in ``flp.score.undoSection()`` when available, so the reversible
    primitive we can expose is FL's own undo stack via ``general.undoUp``.
    """
    from . import protocol

    if _dry_run:
        return _dry_run_plan(tool, "piano_roll_apply", params)
    before = {"undo_backed": True, "note_readback_available": False}
    result = apply()
    restore = {"command": protocol.CMD_GENERAL_UNDO, "params": {}}
    entry = {
        "tool": tool,
        "scope": "piano_roll",
        "command": "piano_roll_apply",
        "params": params,
        "before": before,
        "after": result,
        "echo": result,
        "restore": restore,
        "ts": time.time(),
        "rollback_note": "Uses FL Studio undo for the generated Piano Roll script.",
    }
    entry = _log.append(entry)
    _notify_runtime(bridge, scope="piano_roll", command="piano_roll_apply")
    return {
        "ok": True,
        "change_id": entry["change_id"],
        "rollback": _rollback_guidance(entry),
        "undo": _undo_text(entry["change_id"]),
        "before": before,
        "after": result,
        "rollback_note": "fl_rollback_last_change uses FL Studio undo for this Piano Roll edit",
    }


def safe_write_group(bridge, *, tool, scope, writes, rollback_unit=None):
    """Apply several param writes as ONE rollback unit.

    ``writes`` is a list of dicts, each:
        {"snap_scope": "plugin_param:T:S:I",   # what to snapshot for restore
         "command": CMD, "params": {...},      # the write to execute
         "restore": callable(before)->{"command","params"},  # how to undo it
         "read_scope": "optional override",     # defaults to snap_scope
         "verify": ("field", expected)}         # optional post-write polling

    Validates all write entries, snapshots all scopes, and builds every restore
    before the first mutation. Writes then execute sequentially with fresh
    readback per write. If a later write fails after earlier writes executed,
    this immediately attempts reverse rollback of the executed writes.
    """
    try:
        checked = _validate_group_writes(writes)
    except Exception as exc:
        _raise_group_write_error(
            {
                "ok": False,
                "error": f"{type(exc).__name__}: {exc}",
                "phase": "validation",
                "mutation_started": False,
            }
        )
    if _dry_run:
        return {
            "ok": True,
            "dry_run": True,
            "planned": {
                "tool": tool,
                "rollback_unit": rollback_unit or tool,
                "scope": scope,
                "writes": [{"command": w["command"], "params": w["params"]} for w in checked],
            },
        }

    befores, restores = [], []
    for w in checked:
        try:
            before = take_snapshot(bridge, w["snap_scope"])
        except Exception as exc:
            _raise_group_write_error(
                {
                    "ok": False,
                    "error": f"{type(exc).__name__}: {exc}",
                    "phase": "snapshot",
                    "failed_index": w["index"],
                    "mutation_started": False,
                }
            )
        try:
            restore = _validate_restore_action(w["restore"](before), w["index"])
        except Exception as exc:
            _raise_group_write_error(
                {
                    "ok": False,
                    "error": f"{type(exc).__name__}: {exc}",
                    "phase": "restore",
                    "failed_index": w["index"],
                    "mutation_started": False,
                }
            )
        befores.append(before)
        restores.append(restore)

    afters, echoes, executed = [], [], []
    for w, before, restore in zip(checked, befores, restores, strict=True):
        try:
            executed.append({"index": w["index"], "before": before, "restore": restore})
            echo = bridge.call(w["command"], w["params"])
            echo = _verify_retry(bridge, w["command"], w["params"], echo, w["verify"])
            after = _read_scope_with_poll(bridge, w["read_scope"], verify=w["verify"])
            _require_verified_readback(after, w["verify"], w["index"])
        except Exception as exc:
            rollback = _rollback_executed_group_writes(bridge, executed)
            result = {
                "ok": False,
                "error": f"{type(exc).__name__}: {exc}",
                "phase": "execute",
                "failed_index": w["index"],
                "mutation_started": bool(executed),
                "rollback_attempted": True,
                "partial_rollback": rollback,
            }
            if not rollback["ok"]:
                entry = _log.append(
                    {
                        "tool": tool,
                        "rollback_unit": rollback_unit or tool,
                        "scope": scope,
                        "group": True,
                        "partial_failure": True,
                        "failed_index": w["index"],
                        "error": result["error"],
                        "befores": [item["before"] for item in executed],
                        "restores": [item["restore"] for item in executed],
                        "rollback_attempt": rollback,
                        "ts": time.time(),
                    }
                )
                result["change_id"] = entry["change_id"]
            _raise_group_write_error(result)
        echoes.append(echo)
        afters.append(after)

    entry = _log.append(
        {
            "tool": tool,
            "rollback_unit": rollback_unit or tool,
            "scope": scope,
            "group": True,
            "befores": befores,
            "afters": afters,
            "echoes": echoes,
            "restores": restores,
            "ts": time.time(),
        }
    )
    _notify_runtime(
        bridge,
        scope=scope,
        command=",".join(str(row["command"]) for row in checked),
    )
    return {
        "ok": True,
        "change_id": entry["change_id"],
        "rollback": _rollback_guidance(entry),
        "undo": _undo_text(entry["change_id"]),
        "before": befores,
        "after": afters,
    }


def rollback_last_change(bridge):
    entry = _log.pop_last()
    if entry is None:
        return {"ok": False, "error": "changelog is empty"}
    return _rollback_entry(bridge, entry)


def rollback_change(bridge, change_id: str):
    entry, error = _log.pop_latest_matching(str(change_id))
    if entry is not None:
        return _rollback_entry(bridge, entry)
    if error == "non_lifo":
        return {
            "ok": False,
            "error": "change is not the latest entry; refusing non-LIFO rollback",
            "change_id": change_id,
        }
    if error == "empty":
        return {"ok": False, "error": "changelog is empty", "change_id": change_id}
    return {"ok": False, "error": "change_id not found", "change_id": change_id}


def change_history(limit: int = 10, *, include_payload: bool = False) -> dict:
    entries = _log.recent(limit, include_payload=include_payload)
    return {"ok": True, "count": len(entries), "entries": entries}


def export_change_log(output_path: str | None = None, *, include_payload: bool = True) -> dict:
    return {"ok": True, **_log.export(output_path, include_payload=include_payload)}


def _rollback_entry(bridge, entry: dict):
    change_id = entry.get("change_id")
    if entry.get("group"):  # grouped write -> replay every restore
        restored = [_call_restore(bridge, r) for r in reversed(entry.get("restores") or [])]
        _notify_runtime(bridge, scope=entry.get("scope") or "project")
        return {
            "ok": True,
            "rolled_back": entry.get("tool"),
            "scope": entry.get("scope"),
            "change_id": change_id,
            "restored": restored,
        }
    restore = entry.get("restore")
    if not restore:
        return {
            "ok": False,
            "error": "entry has no restore action",
            "tool": entry.get("tool"),
            "change_id": change_id,
        }
    restored = _call_restore(bridge, restore)
    _notify_runtime(
        bridge,
        scope=entry.get("scope") or "project",
        command=restore.get("command"),
    )
    return {
        "ok": True,
        "rolled_back": entry.get("tool"),
        "scope": entry.get("scope"),
        "change_id": change_id,
        "restored": restored,
    }


def _notify_runtime(bridge, *, scope: str, command: str | None = None) -> None:
    try:
        from .runtime.invalidation import notify_verified_write

        notify_verified_write(bridge, scope=scope, command=command)
    except Exception:
        # A verified FL write must not be reported as failed because a
        # best-effort cache invalidation notification could not be delivered.
        pass

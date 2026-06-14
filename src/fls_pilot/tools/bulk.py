"""Bulk mute/solo -- server-side orchestration over the existing per-track
mute/solo commands. No new controller handlers.

"Solo a group" is implemented as muting the COMPLEMENT (mute every other track):
reliable and reversible, where FL's multi-track solo is inconsistent. Bulk writes
go through safety.safe_write_group as ONE rollback unit; fl_clear_mute_solo is the
universal reset.
"""

from __future__ import annotations

from typing import Annotated

from fastmcp import FastMCP
from pydantic import Field

from .. import protocol, safety, workflow_report
from ..connection import fetch_all_pages, get_bridge
from ..music.mix_doctor import FAMILIES


def _tracks(bridge):
    raw = (fetch_all_pages(bridge, protocol.CMD_MIXER_LIST_TRACKS, "tracks") or {}).get(
        "tracks", []
    )
    return [
        {
            "index": t.get("i", t.get("index")),
            "name": t.get("name") or "",
            "mute": bool(t.get("mute")),
            "solo": bool(t.get("solo")),
        }
        for t in raw
    ]


def resolve_targets(tracks, category=None, names=None):
    """Track indices matching a category (a FAMILIES role, or any name substring)
    and/or an explicit list of names/indices. Master (0) is excluded. PURE."""
    out = set()
    if category:
        c = str(category).lower()
        keywords = FAMILIES.get(c, (c,))  # known role -> its keywords; else literal
        for t in tracks:
            if t["index"] != 0 and any(k in t["name"].lower() for k in keywords):
                out.add(t["index"])
    for spec in names or []:
        if isinstance(spec, int):
            if spec != 0:
                out.add(spec)
        else:
            s = str(spec).lower()
            for t in tracks:
                if t["index"] != 0 and s in t["name"].lower():
                    out.add(t["index"])
    return out


def _mute_writes(indices, state):
    return [
        {
            "snap_scope": f"mixer_track:{i}",
            "command": protocol.CMD_MIXER_SET_MUTE,
            "params": {"track": i, "state": state},
            "restore": (
                lambda b, i=i: {
                    "command": protocol.CMD_MIXER_SET_MUTE,
                    "params": {"track": i, "state": b["mute"]},
                }
            ),
        }
        for i in sorted(indices)
    ]


def _dry_run_report(*, workflow: str, title: str, proposed_changes: list[dict]) -> dict:
    return workflow_report.workflow_report(
        workflow=workflow,
        title=title,
        mode="dry_run",
        status="Dry-run only",
        summary={"proposed_changes": len(proposed_changes), "applied_changes": 0},
        proposed_changes=proposed_changes,
        notes=["Dry-run mode is enabled; no FL Studio project state was changed."],
        safety={"read_only": True, "requires_explicit_approval": True},
    )


def _track_from_state(state: object) -> object:
    if not isinstance(state, dict):
        return "unknown"
    return state.get("track", state.get("index", state.get("i", "unknown")))


def _applied_state_changes(
    res: dict,
    *,
    id_prefix: str,
    title_prefix: str,
    tool: str,
    requested_state: bool,
) -> list[dict]:
    rows = []
    for before, after in zip(res.get("before", []), res.get("after", []), strict=True):
        track = _track_from_state(after)
        rows.append(
            workflow_report.applied_change(
                id=f"{id_prefix}_{track}",
                title=f"{title_prefix} {track}",
                tool=tool,
                before=before,
                requested_change={"track": track, "state": requested_state},
                after=after,
                safety_class="write-safe-required",
                risk_level="low",
                change_id=res.get("change_id"),
                rollback=res.get("rollback"),
                rollback_command=res.get("undo"),
                readback_ok=True,
            )
        )
    return rows


def register(mcp: FastMCP) -> None:
    _WR = {
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": False,
        "openWorldHint": True,
        "safetyClass": "write-safe-required",
    }

    @mcp.tool(annotations={"title": "Solo a group of tracks", **_WR})
    def fl_solo_tracks(
        category: Annotated[
            str | None,
            Field(
                description=(
                    "Role to isolate: 'drums', 'vocals', 'bass', 'synth', 'guitar' "
                    "(or any track-name substring)."
                )
            ),
        ] = None,
        tracks: Annotated[
            list[int | str] | None,
            Field(description="Explicit track indices or name substrings to keep audible."),
        ] = None,
        approved: Annotated[
            bool,
            Field(description="Must be True to apply the state changes. False returns a proposal."),
        ] = False,
    ) -> dict:
        """Isolate a group so only it is audible -- mutes every OTHER (non-Master)
        track. Use category ('drums', etc.) or explicit tracks. Implemented as
        mute-the-rest (reliable; FL's multi-solo is inconsistent). Reverse with
        fl_clear_mute_solo. One rollback unit.

        Safety: Write-Safe-Required with Rollback.
        """
        if not category and not tracks:
            return workflow_report.workflow_report(
                workflow="bulk_solo_tracks",
                title="Solo Tracks",
                mode="error",
                status="Error",
                summary="give a category or a tracks list",
                ok=False,
            )
        b = get_bridge()
        ts = _tracks(b)
        keep = resolve_targets(ts, category, tracks)
        if not keep:
            return workflow_report.workflow_report(
                workflow="bulk_solo_tracks",
                title="Solo Tracks",
                mode="error",
                status="Error",
                summary={"error": "no tracks matched", "category": category, "tracks": tracks},
                ok=False,
            )
        to_mute = [
            t["index"] for t in ts if t["index"] != 0 and not t["mute"] and t["index"] not in keep
        ]
        if not to_mute:
            return workflow_report.workflow_report(
                workflow="bulk_solo_tracks",
                title="Solo Tracks",
                mode="no_op",
                status="No changes needed",
                summary={"kept": sorted(keep), "note": "everything else was already muted"},
                ok=True,
            )
        proposal = workflow_report.proposed_change(
            id="bulk_solo_tracks",
            title="Solo tracks",
            tool="fl_solo_tracks",
            observed_state={"tracks_to_mute": len(to_mute)},
            proposed_state={
                "category": category,
                "tracks": tracks,
                "approved": True,
            },
            safety_class="write-safe-required",
            risk_level="low",
            readback_expectation="Mute states read back matching applied writes",
            rollback_expectation="One named rollback unit",
        )
        if not approved:
            return workflow_report.approval_required_report(
                workflow="bulk_solo_tracks",
                title="Solo Tracks",
                proposed_changes=[proposal],
            )
        try:
            res = safety.safe_write_group(
                b,
                tool="bulk_solo",
                scope="mixer:bulk",
                writes=_mute_writes(to_mute, True),
                rollback_unit="bulk_solo_tracks",
            )
        except Exception as e:
            return workflow_report.workflow_report(
                workflow="bulk_solo_tracks",
                title="Solo Tracks",
                mode="error",
                status="Error",
                summary=f"{type(e).__name__}: {e}",
                ok=False,
            )
        if res.get("dry_run"):
            return _dry_run_report(
                workflow="bulk_solo_tracks",
                title="Solo Tracks",
                proposed_changes=[proposal],
            )

        applied_changes = _applied_state_changes(
            res,
            id_prefix="bulk_solo_tracks",
            title_prefix="Mute track",
            tool="fl_solo_tracks",
            requested_state=True,
        )

        return workflow_report.workflow_report(
            workflow="bulk_solo_tracks",
            title="Solo Tracks",
            mode="applied",
            status="Tracks soloed",
            applied_changes=applied_changes,
            notes=["fl_clear_mute_solo to restore"],
        )

    @mcp.tool(annotations={"title": "Mute a group of tracks", **_WR})
    def fl_mute_tracks(
        category: Annotated[
            str | None, Field(description="Role to mute (or any track-name substring).")
        ] = None,
        tracks: Annotated[
            list[int | str] | None,
            Field(description="Explicit track indices or name substrings to mute."),
        ] = None,
        approved: Annotated[
            bool,
            Field(description="Must be True to apply the state changes. False returns a proposal."),
        ] = False,
    ) -> dict:
        """Mute a group of tracks (leaves the others as they are). Use category or
        explicit tracks. One rollback unit; reverse with fl_clear_mute_solo.

        Safety: Write-Safe-Required with Rollback.
        """
        if not category and not tracks:
            return workflow_report.workflow_report(
                workflow="bulk_mute_tracks",
                title="Mute Tracks",
                mode="error",
                status="Error",
                summary="give a category or a tracks list",
                ok=False,
            )
        b = get_bridge()
        ts = _tracks(b)
        targets = resolve_targets(ts, category, tracks)
        muted_now = {t["index"] for t in ts if t["mute"]}
        to_mute = [i for i in sorted(targets) if i not in muted_now]
        if not to_mute:
            return workflow_report.workflow_report(
                workflow="bulk_mute_tracks",
                title="Mute Tracks",
                mode="no_op",
                status="No changes needed",
                summary={"muted": [], "note": "matched tracks already muted, or none matched"},
                ok=True,
            )
        proposal = workflow_report.proposed_change(
            id="bulk_mute_tracks",
            title="Mute tracks",
            tool="fl_mute_tracks",
            observed_state={"tracks_to_mute": len(to_mute)},
            proposed_state={
                "category": category,
                "tracks": tracks,
                "approved": True,
            },
            safety_class="write-safe-required",
            risk_level="low",
            readback_expectation="Mute states read back matching applied writes",
            rollback_expectation="One named rollback unit",
        )
        if not approved:
            return workflow_report.approval_required_report(
                workflow="bulk_mute_tracks",
                title="Mute Tracks",
                proposed_changes=[proposal],
            )
        try:
            res = safety.safe_write_group(
                b,
                tool="bulk_mute",
                scope="mixer:bulk",
                writes=_mute_writes(to_mute, True),
                rollback_unit="bulk_mute_tracks",
            )
        except Exception as e:
            return workflow_report.workflow_report(
                workflow="bulk_mute_tracks",
                title="Mute Tracks",
                mode="error",
                status="Error",
                summary=f"{type(e).__name__}: {e}",
                ok=False,
            )
        if res.get("dry_run"):
            return _dry_run_report(
                workflow="bulk_mute_tracks",
                title="Mute Tracks",
                proposed_changes=[proposal],
            )

        applied_changes = _applied_state_changes(
            res,
            id_prefix="bulk_mute_tracks",
            title_prefix="Mute track",
            tool="fl_mute_tracks",
            requested_state=True,
        )

        return workflow_report.workflow_report(
            workflow="bulk_mute_tracks",
            title="Mute Tracks",
            mode="applied",
            status="Tracks muted",
            applied_changes=applied_changes,
            notes=["fl_clear_mute_solo to restore"],
        )

    @mcp.tool(annotations={"title": "Clear all mutes + solos", **_WR})
    def fl_clear_mute_solo(
        approved: Annotated[
            bool,
            Field(description="Must be True to apply the state changes. False returns a proposal."),
        ] = False,
    ) -> dict:
        """Unmute and unsolo every mixer track (reset). The universal undo for the
        bulk solo/mute tools.

        Safety: Write-Safe-Required with Rollback.
        """
        b = get_bridge()
        ts = _tracks(b)
        writes = []
        for t in ts:
            i = t["index"]
            if t["mute"]:
                writes.append(
                    {
                        "snap_scope": f"mixer_track:{i}",
                        "command": protocol.CMD_MIXER_SET_MUTE,
                        "params": {"track": i, "state": False},
                        "restore": (
                            lambda b, i=i: {
                                "command": protocol.CMD_MIXER_SET_MUTE,
                                "params": {"track": i, "state": b["mute"]},
                            }
                        ),
                    }
                )
            if t["solo"]:
                writes.append(
                    {
                        "snap_scope": f"mixer_track:{i}",
                        "command": protocol.CMD_MIXER_SET_SOLO,
                        "params": {"track": i, "state": False},
                        "restore": (
                            lambda b, i=i: {
                                "command": protocol.CMD_MIXER_SET_SOLO,
                                "params": {"track": i, "state": b["solo"]},
                            }
                        ),
                    }
                )
        if not writes:
            return workflow_report.workflow_report(
                workflow="clear_mute_solo",
                title="Clear Mute/Solo",
                mode="no_op",
                status="No changes needed",
                summary={"cleared": 0, "note": "no mutes or solos were set"},
                ok=True,
            )
        proposal = workflow_report.proposed_change(
            id="clear_mute_solo",
            title="Clear all mutes and solos",
            tool="fl_clear_mute_solo",
            observed_state={"items_to_clear": len(writes)},
            proposed_state={"approved": True},
            safety_class="write-safe-required",
            risk_level="low",
            readback_expectation="Mute/solo states read back as False",
            rollback_expectation="One named rollback unit",
        )
        if not approved:
            return workflow_report.approval_required_report(
                workflow="clear_mute_solo",
                title="Clear Mute/Solo",
                proposed_changes=[proposal],
            )
        try:
            res = safety.safe_write_group(
                b,
                tool="clear_mute_solo",
                scope="mixer:bulk",
                writes=writes,
                rollback_unit="clear_mute_solo",
            )
        except Exception as e:
            return workflow_report.workflow_report(
                workflow="clear_mute_solo",
                title="Clear Mute/Solo",
                mode="error",
                status="Error",
                summary=f"{type(e).__name__}: {e}",
                ok=False,
            )
        if res.get("dry_run"):
            return _dry_run_report(
                workflow="clear_mute_solo",
                title="Clear Mute/Solo",
                proposed_changes=[proposal],
            )

        applied_changes = _applied_state_changes(
            res,
            id_prefix="clear_mute_solo",
            title_prefix="Clear mute/solo on track",
            tool="fl_clear_mute_solo",
            requested_state=False,
        )

        return workflow_report.workflow_report(
            workflow="clear_mute_solo",
            title="Clear Mute/Solo",
            mode="applied",
            status="Mutes and solos cleared",
            applied_changes=applied_changes,
        )

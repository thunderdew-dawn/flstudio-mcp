"""Routing / grouping / cleanup tools -- Slice 1: READ ONLY.

Reports the mixer routing matrix, channel->mixer assignments, and flags
cleanup candidates (empty channels / unused mixer tracks). No writes, no
renames, no deletes -- that's a later slice.

Design: the CONTROLLER only returns cheap RAW data (per-channel name+target,
per-track name+routes, per-track plugin slots). All empty/unused JUDGEMENT
happens HERE on the server (plain Python, no sandbox loop limit), aggregating
several cheap controller reads -- instead of asking the controller to scan
everything in a single OnSysEx tick (which stalls FL).
"""

from __future__ import annotations

from typing import Annotated

from fastmcp import FastMCP
from pydantic import Field

from .. import kb_policy, operations, protocol, safety, workflow_report
from .. import project_templates as templates
from ..analysis import (
    EVIDENCE_TYPE_ROUTING_BASED_DETECTION,
    get_analysis_broker,
    heuristic_validation_metadata,
    routing_analysis_report_from_legacy_payload,
    serialize_analysis_report,
)
from ..connection import fetch_all_pages, get_bridge
from ..runtime.interactions import InteractionRequest
from .registration import RETIRED_LOW_LEVEL_TOOLS, hide_retired_tools
from .targets import mixer_track_error


def _route_write_entry(src: int, dst: int, enabled: bool) -> dict:
    """One safe_write_group entry that sets a route and restores its prior state."""
    return operations.prepare_operation(
        "mixer", "set_route", {"src": src, "dst": dst, "enabled": enabled}
    ).safe_write_group_entry()


def _bus_rename_entry(bus: int, name: str) -> dict:
    """One safe_write_group entry that renames a track and restores its old name."""
    return operations.prepare_operation(
        "mixer", "set_name", {"track": bus, "name": name}
    ).safe_write_group_entry()


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


def _no_write_report(*, workflow: str, title: str, status: str, ok: bool = True) -> dict:
    return workflow_report.workflow_report(
        workflow=workflow,
        title=title,
        mode="no_op" if ok else "error",
        status=status,
        summary={"applied_changes": 0},
        notes=["No FL Studio project state was changed."],
        ok=ok,
    )


# --- server-side judgement helpers (pure) -----------------------------------
def _looks_default_channel_name(name) -> bool:
    if not name:
        return True
    return str(name).split(" ")[0] in ("Channel", "Sampler", "Insert")


def _is_default_mixer_name(i, name) -> bool:
    name = name or ""
    if i == 0:
        return name in ("", "Master")
    return name in ("", f"Insert {i}")


def _routing_review_findings(
    *,
    unrouted_channels: list[dict],
    direct_to_master: list[dict],
) -> list[dict]:
    findings = []
    if unrouted_channels:
        findings.append(
            {
                "id": "unrouted_channels",
                "severity": "critical",
                "title": "Unrouted Channels",
                "detail": "Channels without a usable mixer target may bypass routing review.",
                "count": len(unrouted_channels),
                "items": unrouted_channels[:8],
            }
        )
    if direct_to_master:
        findings.append(
            {
                "id": "generators_direct_to_master",
                "severity": "warning",
                "title": "Generators Direct to Master",
                "detail": "Generator channels route through inserts that feed Master directly.",
                "count": len(direct_to_master),
                "items": direct_to_master[:8],
                "metadata": heuristic_validation_metadata(
                    evidence_type=EVIDENCE_TYPE_ROUTING_BASED_DETECTION,
                    interaction_request_id="routing.confirm_cleanup_heuristics",
                    reason="master_routed_or_ungrouped",
                ),
            }
        )
    if not findings:
        findings.append(
            {
                "id": "routing_clear",
                "severity": "ok",
                "title": "No Routing Blockers Detected",
                "detail": "The static routing review did not find direct blockers.",
                "count": 0,
                "items": [],
            }
        )
    return findings


def _routing_validation_request(findings: list[dict]) -> dict | None:
    options = [
        {
            "id": str(row.get("id")),
            "label": str(row.get("title") or row.get("id")),
            "count": int(row.get("count") or 0),
            "reason": dict(row.get("metadata") or {}).get("reason"),
        }
        for row in findings
        if isinstance(row.get("metadata"), dict)
        and row["metadata"].get("human_validation_required")
    ]
    if not options:
        return None
    return InteractionRequest(
        id="routing.confirm_cleanup_heuristics",
        type="multi_select",
        title="Confirm routing cleanup candidates",
        prompt="Which routing findings are intentional before cleanup planning is final?",
        options=tuple(options),
        allow_remove=True,
        metadata={
            "reason": EVIDENCE_TYPE_ROUTING_BASED_DETECTION,
            "finding_ids": [row["id"] for row in options],
        },
    ).to_dict()


def detect_cleanup(bridge, *, max_plugin_checks: int = 60) -> dict:
    """Aggregate cheap controller reads and decide cleanup candidates here.

    Steps (all cheap controller calls, each its own round trip):
      1. channel_routing_summary -> which mixer tracks have a channel feeding them
      2. mixer_get_routing_all   -> track names + who routes INTO each (derived)
      3. plugin_list(track)      -> ONLY for surviving candidate tracks
    Empty-channel detection is a name heuristic (the API can't cheaply see
    clip/piano-roll content); unused-mixer-track detection is reliable.
    """
    chans = fetch_all_pages(bridge, protocol.CMD_CHANNEL_ROUTING_SUMMARY, "channels")
    routing = fetch_all_pages(bridge, protocol.CMD_MIXER_GET_ROUTING_ALL, "routing")
    tracks = routing.get("routing", [])
    template_context = templates.classify_topology(tracks, tracks, chans.get("channels", []))

    targeted = set()
    for c in chans.get("channels", []):
        tgt = c.get("target_mixer_track")
        if isinstance(tgt, int):
            targeted.add(tgt)

    # incoming routes derived from the matrix -- no extra controller calls.
    incoming: dict = {}
    for r in tracks:
        for d in r.get("routes_to", []):
            incoming.setdefault(d.get("dst"), []).append(r.get("i"))

    empty = [
        {"channel": c.get("channel"), "name": c.get("name")}
        for c in chans.get("channels", [])
        if _looks_default_channel_name(c.get("name"))
    ]

    unused = []
    checks = 0
    truncated = False
    for r in tracks:
        i = r.get("i")
        if i == 0 or i in targeted:  # Master, or a channel feeds it
            continue
        if templates.is_reserved_placeholder(template_context, i):
            continue
        if not _is_default_mixer_name(i, r.get("name")):
            continue  # named -> intentional
        if incoming.get(i):  # a send feeds it -> a bus
            continue
        if checks >= max_plugin_checks:
            truncated = True
            break
        checks += 1
        if bridge.call(protocol.CMD_PLUGIN_LIST, {"track": i}).get("slots"):
            continue  # has a plugin -> in use
        unused.append({"track": i, "name": r.get("name")})

    return {
        "channel_emptiness_reliable": False,
        "empty_channel_criteria": [
            "default-looking name (NAME heuristic -- clip/piano-roll content NOT checked)"
        ],
        "empty_channel_candidates": empty,
        "unused_mixer_track_criteria": [
            "no channel linked",
            "default name",
            "no sends routed in",
            "no plugins",
            "not a recognized template-reserved placeholder",
        ],
        "unused_mixer_tracks": unused,
        "unused_mixer_track_truncated": truncated,
        "template_context": templates.compact_context(template_context),
        "note": "READ-ONLY. Judgement done server-side from cheap controller "
        "reads. Unused tracks reliable; channel emptiness is a name "
        "heuristic. Recognized template reservations are preserved. Verify "
        "before any delete (Slice 2).",
    }


def register(mcp: FastMCP) -> None:
    mcp = hide_retired_tools(mcp, RETIRED_LOW_LEVEL_TOOLS)
    _RO = {
        "readOnlyHint": True,
        "idempotentHint": True,
        "openWorldHint": True,
        "safetyClass": "read-only",
    }
    _WR = {
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
        "safetyClass": "write-safe-required",
    }

    @mcp.tool(annotations={"title": "Get mixer track routing", **_RO})
    def fl_get_routing(
        track: Annotated[int, Field(ge=0, description="Mixer track index (0 = Master).")],
    ) -> dict:
        """Which destination tracks this mixer track sends to:
        {track, name, routes_to:[{dst, dst_name, level?}]}.

        Safety: Read-Only.
        """
        return get_bridge().call(protocol.CMD_MIXER_GET_ROUTING, {"track": track})

    @mcp.tool(annotations={"title": "Get full routing matrix", **_RO})
    def fl_get_routing_all() -> dict:
        """Routing for every mixer track (paginated under the hood, returned
        whole): {total, routing:[{i, name, routes_to:[...]}]}.

        Safety: Read-Only.
        """
        return fetch_all_pages(get_bridge(), protocol.CMD_MIXER_GET_ROUTING_ALL, "routing")

    @mcp.tool(annotations={"title": "Get channel->mixer routing", **_RO})
    def fl_get_channel_routing() -> dict:
        """Which mixer track each channel-rack channel is linked to:
        {total, channels:[{channel, name, target_mixer_track, target_name}]}.

        Safety: Read-Only.
        """
        return fetch_all_pages(get_bridge(), protocol.CMD_CHANNEL_ROUTING_SUMMARY, "channels")

    @mcp.tool(annotations={"title": "Detect cleanup candidates (read-only)", **_RO})
    def fl_detect_cleanup_candidates() -> dict:
        """Flag (do NOT touch) empty channels + unused mixer tracks, each with a
        reason. Judgement is computed server-side from cheap controller reads.
        Channel emptiness is a name heuristic; unused-track detection is reliable.

        Safety: Read-Only.
        """
        return detect_cleanup(get_bridge())

    @mcp.tool(annotations={"title": "Set mixer routing (src -> dst)", **_WR})
    def fl_set_route(
        src: Annotated[int, Field(ge=0, description="Source mixer track.")],
        dst: Annotated[int, Field(ge=0, description="Destination mixer track (0 = Master).")],
        enabled: Annotated[bool, Field(description="True = route on, False = off.")] = True,
    ) -> dict:
        """Enable/disable a send from src -> dst (calls afterRoutingChanged on the
        FL side). Snapshot + readback; undo with fl_rollback_last_change.

        Safety: Write-Safe-Required with Rollback.
        """
        bridge = get_bridge()
        for track, purpose in ((src, "mixer route source"), (dst, "mixer route destination")):
            error = mixer_track_error(bridge, track, purpose=purpose)
            if error is not None:
                return error
        return safety.safe_write(
            bridge,
            tool="mixer_set_route",
            scope=f"route:{src}:{dst}",
            command=protocol.CMD_MIXER_SET_ROUTE,
            params={"src": src, "dst": dst, "enabled": enabled},
            verify=("enabled", enabled),
            build_restore=lambda b: {
                "command": protocol.CMD_MIXER_SET_ROUTE,
                "params": {"src": src, "dst": dst, "enabled": b["enabled"]},
            },
        )

    @mcp.tool(annotations={"title": "Group tracks into a bus", **_WR})
    def fl_group_tracks(
        sources: Annotated[
            list[int], Field(description="Source mixer tracks to route into the bus.")
        ],
        bus: Annotated[int, Field(ge=1, description="Destination bus mixer track (not Master).")],
        name: Annotated[
            str | None, Field(description="Optional new name for the bus track.")
        ] = None,
        approved: Annotated[
            bool, Field(description="Must be True to apply the group routing.")
        ] = False,
    ) -> dict:
        """Group sources into a bus, EXCLUSIVELY: each source -> bus ON and its
        direct -> Master OFF; bus -> Master ON; optional bus rename. Applied as
        ONE rollback unit -- fl_rollback_last_change undoes the whole grouping.

        Safety: Write-Safe-Required with Rollback. The routing and optional rename are
        persisted as one named rollback unit.
        """
        proposal = workflow_report.proposed_change(
            id="group_tracks",
            title="Group tracks to bus",
            tool="fl_group_tracks",
            observed_state={},
            proposed_state={
                "sources": sources,
                "bus": bus,
                "name": name,
                "approved": True,
            },
            safety_class="write-safe-required",
            risk_level="medium",
            readback_expectation="Routes and name read back matching applied writes",
            rollback_expectation="One named rollback unit for the group operation",
        )
        if not approved:
            return workflow_report.approval_required_report(
                workflow="group_tracks",
                title="Group Tracks",
                proposed_changes=[proposal],
            )

        bridge = get_bridge()
        error = mixer_track_error(bridge, bus, allow_master=False, purpose="group bus track")
        if error is not None:
            return error
        srcs = [int(s) for s in sources if int(s) not in (bus, 0)]
        for src in srcs:
            error = mixer_track_error(bridge, src, allow_master=False, purpose="group source track")
            if error is not None:
                return error
        writes = []
        for s in srcs:
            writes.append(_route_write_entry(s, bus, True))  # source -> bus ON
            writes.append(_route_write_entry(s, 0, False))  # source -> Master OFF
        writes.append(_route_write_entry(bus, 0, True))  # bus -> Master ON
        if name:
            writes.append(_bus_rename_entry(bus, name))
        if not srcs:
            return _no_write_report(
                workflow="group_tracks",
                title="Group Tracks",
                status="No valid source tracks (excluding bus and Master)",
                ok=False,
            )
        res = safety.safe_write_group(
            bridge,
            tool="group_tracks",
            scope=f"group:bus{bus}",
            writes=writes,
            rollback_unit=f"group_tracks_bus_{bus}",
        )
        if res.get("dry_run"):
            return _dry_run_report(
                workflow="group_tracks",
                title="Group Tracks",
                proposed_changes=[proposal],
            )

        applied_changes = []
        if not res.get("dry_run") and "after" in res:
            applied_changes.append(
                workflow_report.applied_change(
                    id="group_tracks",
                    title="Group tracks to bus",
                    tool="fl_group_tracks",
                    before=res.get("before"),
                    requested_change={"sources": srcs, "bus": bus, "name": name},
                    after=res.get("after"),
                    safety_class="write-safe-required",
                    risk_level="medium",
                    change_id=res.get("change_id"),
                    rollback=res.get("rollback"),
                    rollback_command=res.get("undo"),
                    readback_ok=True,
                )
            )

        return workflow_report.workflow_report(
            workflow="group_tracks",
            title="Group Tracks",
            mode="applied",
            status="Tracks grouped",
            applied_changes=applied_changes,
        )

    # --- Phase 1: Routing Review 2.0 ---

    @mcp.tool(annotations={"title": "Review routing", **_RO})
    def fl_review_routing() -> dict:
        """Analyze project routing to find structural issues like generators routed to Master,
        unrouted channels, or missing bus structures.

        Safety: Read-Only.
        """
        bridge = get_bridge()
        snapshot = get_analysis_broker().get_static_project_snapshot(bridge)
        channels = list(snapshot.channels)
        tracks = list(snapshot.routing)
        template_context = snapshot.template_context

        unrouted = []
        direct_to_master = []

        # Track routing map
        track_to_master = {}
        for t in tracks:
            routes = t.get("routes_to", [])
            track_to_master[t.get("i")] = any(r.get("dst") == 0 for r in routes)

        for c in channels:
            tgt = c.get("target_mixer_track")
            ctype = c.get("type", {}).get("label")

            if not isinstance(tgt, int) or tgt == 0:
                if ctype != "unknown":
                    unrouted.append(
                        {"channel": c.get("channel"), "name": c.get("name"), "type": ctype}
                    )
            else:
                if (
                    track_to_master.get(tgt)
                    and ctype == "genplug"
                    and not templates.is_template_bus(template_context, tgt)
                ):
                    direct_to_master.append(
                        {
                            "channel": c.get("channel"),
                            "name": c.get("name"),
                            "mixer_track": tgt,
                            "mixer_name": next(
                                (t.get("name") for t in tracks if t.get("i") == tgt),
                                f"Insert {tgt}",
                            ),
                        }
                    )

        findings = _routing_review_findings(
            unrouted_channels=unrouted,
            direct_to_master=direct_to_master,
        )
        interaction_request = _routing_validation_request(findings)
        legacy_payload = {
            "ok": True,
            "workflow": "routing_review",
            "title": "Routing Review",
            "summary": {
                "channels": len(channels),
                "mixer_tracks": len(tracks),
                "unrouted_channels": len(unrouted),
                "generators_direct_to_master": len(direct_to_master),
            },
            "findings": findings,
            "unrouted_channels": unrouted,
            "generators_direct_to_master": direct_to_master,
            "interaction_requests": (
                [interaction_request] if interaction_request is not None else []
            ),
            "template_context": templates.compact_context(template_context),
            "note": "Use this data to plan bus structures or correct routing.",
            "details": {
                "channels": [
                    {
                        "channel": c.get("channel"),
                        "name": c.get("name"),
                        "type": c.get("type"),
                        "target_mixer_track": c.get("target_mixer_track"),
                        "target_name": c.get("target_name"),
                    }
                    for c in channels
                ],
                "routes": tracks,
                "template_context": templates.compact_context(template_context),
                "project_fingerprint": snapshot.project_fingerprint,
                "source_observation_ids": list(snapshot.source_observation_ids),
                "policy_notes": [
                    "Preserve recognizable existing routing structure before proposing cleanup.",
                    (
                        "Infer Channel Rack to Mixer relationships from channel "
                        "target tracks, not playlist indices."
                    ),
                    (
                        "Treat plugin insertion, external inputs, and UI drag-and-drop "
                        "routing as manual guidance."
                    ),
                ],
            },
            "policy_notes": [
                "Preserve recognizable existing routing structure before proposing cleanup.",
                (
                    "Infer Channel Rack to Mixer relationships from channel "
                    "target tracks, not playlist indices."
                ),
                (
                    "Treat plugin insertion, external inputs, and UI drag-and-drop "
                    "routing as manual guidance."
                ),
            ],
            "kb_policy_refs": kb_policy.rule_refs(
                [
                    "preserve_existing_structure_first",
                    "channel_rack_workflow_requires_routing_inference",
                    "routing_ui_guidance_vs_mcp_write",
                ]
            ),
            "safety": {"read_only": True, "project_changes": False},
        }
        report = serialize_analysis_report(
            routing_analysis_report_from_legacy_payload(
                legacy_payload,
                workflow="routing_review",
                title="Routing Review",
            )
        )
        report["unrouted_channels"] = unrouted
        report["generators_direct_to_master"] = direct_to_master
        report["template_context"] = legacy_payload["template_context"]
        report["note"] = legacy_payload["note"]
        report["policy_notes"] = legacy_payload["policy_notes"]
        report["kb_policy_refs"] = legacy_payload["kb_policy_refs"]
        report["metadata"]["legacy_routing_review"] = {
            "unrouted_channels": unrouted,
            "generators_direct_to_master": direct_to_master,
            "template_context": legacy_payload["template_context"],
        }
        return report

    @mcp.tool(annotations={"title": "Plan routing cleanup", **_RO})
    def fl_plan_routing_cleanup(
        issues: Annotated[list[str], Field(description="List of issues identified to fix")],
        proposed_buses: Annotated[
            list[dict], Field(description="Buses to create (track, name, sources)")
        ],
    ) -> dict:
        """Create a dry-run plan for routing fixes.

        Safety: Read-Only (Dry-run).
        """
        proposed_changes = []
        if issues:
            proposed_changes.append(
                workflow_report.proposed_change(
                    id="fix_routing_issues",
                    title="Fix identified routing issues",
                    tool="fl_apply_routing_cleanup",
                    observed_state={"issues": issues},
                    proposed_state={"issues_resolved": True},
                    safety_class="write-safe-required",
                    risk_level="medium",
                    readback_expectation="Routes read back matching applied writes",
                    rollback_expectation="One named rollback unit for the batch",
                )
            )
        if proposed_buses:
            proposed_changes.append(
                workflow_report.proposed_change(
                    id="create_buses",
                    title="Create routing buses",
                    tool="fl_apply_bus_layout",
                    observed_state={"buses_missing": len(proposed_buses)},
                    proposed_state={"buses": proposed_buses},
                    safety_class="write-safe-required",
                    risk_level="medium",
                    readback_expectation="Routes and names read back matching applied writes",
                    rollback_expectation="One named rollback unit per layout",
                )
            )

        return workflow_report.workflow_report(
            workflow="routing_cleanup_plan",
            title="Routing Cleanup Plan",
            mode="dry_run",
            status="Plan created. Please review and apply using fl_apply_routing_cleanup.",
            proposed_changes=proposed_changes,
            kb_policy_refs=kb_policy.rule_refs(
                [
                    "preserve_existing_structure_first",
                    "channel_rack_workflow_requires_routing_inference",
                    "routing_ui_guidance_vs_mcp_write",
                    "send_effects_for_shared_space",
                ]
            ),
            metadata={
                "issues": issues,
                "proposed_buses": proposed_buses,
                "rules": [
                    "Preserve existing structure when it is recognizable.",
                    "Do not infer Playlist Track N maps to Mixer Track N.",
                    "Prefer bus placement before the group when it fits the current project.",
                    "Use one named rollback unit for approved grouped routing writes.",
                    "Keep plugin loading, external I/O, and broad UI routing manual.",
                ],
                "supported_bus_placement_policy": [
                    "before_group",
                    "after_group",
                    "central_front",
                    "central_end",
                    "preserve_existing",
                ],
            },
        )

    @mcp.tool(annotations={"title": "Apply routing cleanup", **_WR})
    def fl_apply_routing_cleanup(
        routes: Annotated[
            list[dict], Field(description="List of route writes: {src, dst, enabled}")
        ],
        renames: Annotated[
            list[dict], Field(description="List of bus renames: {track, name}")
        ] = None,
        approved: Annotated[
            bool, Field(description="Must be True to apply the routing changes.")
        ] = False,
    ) -> dict:
        """Apply multiple routing changes and track renames in one rollback unit.

        Safety: Write-Safe-Required with Rollback.
        """
        proposal = workflow_report.proposed_change(
            id="apply_routing_cleanup",
            title="Apply routing cleanup batch",
            tool="fl_apply_routing_cleanup",
            observed_state={},
            proposed_state={
                "routes": routes,
                "renames": renames,
                "approved": True,
            },
            safety_class="write-safe-required",
            risk_level="medium",
            readback_expectation="Routes read back matching applied writes",
            rollback_expectation="One named rollback unit for the batch",
        )
        if not approved:
            return workflow_report.approval_required_report(
                workflow="apply_routing_cleanup",
                title="Apply Routing Cleanup",
                proposed_changes=[proposal],
            )

        bridge = get_bridge()
        writes = []

        for r in routes:
            writes.append(_route_write_entry(r["src"], r["dst"], r.get("enabled", True)))

        if renames:
            for r in renames:
                writes.append(_bus_rename_entry(r["track"], r["name"]))

        if not writes:
            return _no_write_report(
                workflow="apply_routing_cleanup",
                title="Apply Routing Cleanup",
                status="No writes specified",
            )

        res = safety.safe_write_group(
            bridge,
            tool="apply_routing_cleanup",
            scope="routing_review",
            writes=writes,
            rollback_unit="routing_cleanup_batch",
        )
        if res.get("dry_run"):
            return _dry_run_report(
                workflow="apply_routing_cleanup",
                title="Apply Routing Cleanup",
                proposed_changes=[proposal],
            )

        applied_changes = []
        if not res.get("dry_run") and "after" in res:
            applied_changes.append(
                workflow_report.applied_change(
                    id="apply_routing_cleanup",
                    title="Apply routing cleanup batch",
                    tool="fl_apply_routing_cleanup",
                    before=res.get("before"),
                    requested_change={"routes": routes, "renames": renames},
                    after=res.get("after"),
                    safety_class="write-safe-required",
                    risk_level="medium",
                    change_id=res.get("change_id"),
                    rollback=res.get("rollback"),
                    rollback_command=res.get("undo"),
                    readback_ok=True,
                )
            )

        return workflow_report.workflow_report(
            workflow="apply_routing_cleanup",
            title="Apply Routing Cleanup",
            mode="applied",
            status="Cleanup applied",
            applied_changes=applied_changes,
            kb_policy_refs=kb_policy.rule_refs(
                ["routing_ui_guidance_vs_mcp_write", "send_effects_for_shared_space"]
            ),
        )

    @mcp.tool(annotations={"title": "Apply bus layout", **_WR})
    def fl_apply_bus_layout(
        buses: Annotated[
            list[dict],
            Field(
                description=(
                    "List of bus configs: {bus_track: int, name: str, source_tracks: list[int]}"
                )
            ),
        ],
        approved: Annotated[
            bool, Field(description="Must be True to apply the bus layout.")
        ] = False,
    ) -> dict:
        """Create multiple group buses at once. Ensures each source track sends exclusively to
        its assigned bus, and the bus routes to the Master.

        Policy:
        - Preserve existing structure where recognizable.
        - Prefer buses before their group when that fits the project.
        - Keep UI-only routing and plugin insertion manual.

        Safety: Write-Safe-Required with Rollback.
        """
        proposal = workflow_report.proposed_change(
            id="apply_bus_layout",
            title="Apply bus layout",
            tool="fl_apply_bus_layout",
            observed_state={},
            proposed_state={
                "buses": buses,
                "approved": True,
            },
            safety_class="write-safe-required",
            risk_level="medium",
            readback_expectation="Routes and names read back matching applied writes",
            rollback_expectation="One named rollback unit for the layout",
        )
        if not approved:
            return workflow_report.approval_required_report(
                workflow="apply_bus_layout",
                title="Apply Bus Layout",
                proposed_changes=[proposal],
            )

        bridge = get_bridge()
        writes = []

        for b in buses:
            bus = b["bus_track"]
            name = b.get("name")
            srcs = [int(s) for s in b.get("source_tracks", []) if int(s) not in (bus, 0)]

            for s in srcs:
                writes.append(_route_write_entry(s, bus, True))  # source -> bus ON
                writes.append(_route_write_entry(s, 0, False))  # source -> Master OFF
            writes.append(_route_write_entry(bus, 0, True))  # bus -> Master ON

            if name:
                writes.append(_bus_rename_entry(bus, name))

        if not writes:
            return _no_write_report(
                workflow="apply_bus_layout",
                title="Apply Bus Layout",
                status="No bus writes specified",
            )

        res = safety.safe_write_group(
            bridge,
            tool="create_bus_layout",
            scope="bus_layout",
            writes=writes,
            rollback_unit="bus_layout_creation",
        )
        if res.get("dry_run"):
            return _dry_run_report(
                workflow="apply_bus_layout",
                title="Apply Bus Layout",
                proposed_changes=[proposal],
            )

        applied_changes = []
        if not res.get("dry_run") and "after" in res:
            applied_changes.append(
                workflow_report.applied_change(
                    id="apply_bus_layout",
                    title="Apply bus layout",
                    tool="fl_apply_bus_layout",
                    before=res.get("before"),
                    requested_change={"buses": buses},
                    after=res.get("after"),
                    safety_class="write-safe-required",
                    risk_level="medium",
                    change_id=res.get("change_id"),
                    rollback=res.get("rollback"),
                    rollback_command=res.get("undo"),
                    readback_ok=True,
                )
            )

        return workflow_report.workflow_report(
            workflow="apply_bus_layout",
            title="Apply Bus Layout",
            mode="applied",
            status="Bus layout applied",
            applied_changes=applied_changes,
            kb_policy_refs=kb_policy.rule_refs(
                [
                    "preserve_existing_structure_first",
                    "routing_ui_guidance_vs_mcp_write",
                    "send_effects_for_shared_space",
                ]
            ),
        )

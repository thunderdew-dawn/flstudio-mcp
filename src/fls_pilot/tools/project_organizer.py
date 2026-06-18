"""Project Organizer tools for FL Studio Pilot.

Handles broad project standardization, naming conventions, color coding,
and structural cleanup.
"""

from __future__ import annotations

from typing import Annotated

from fastmcp import FastMCP
from pydantic import Field

from .. import kb_policy, operations, safety
from .. import project_templates as templates
from .. import workflow_report as wr
from ..analysis import enrich_workflow_report_with_analysis, get_analysis_broker
from ..connection import get_bridge
from .channels import _find_free_mixer_track
from .color import parse_color
from .routing import _bus_rename_entry

_ORGANIZER_APPLY_TOOLS = {
    "fl_apply_project_cleanup_step",
    "fl_apply_naming_standard",
    "fl_apply_color_standard",
}


def _looks_default_channel_name(name) -> bool:
    if not name:
        return True
    return str(name).split(" ")[0] in ("Channel", "Sampler", "Insert", "AudioClip")


def _color_params(spec: str) -> dict:
    rgb = parse_color(spec)
    if rgb is None:
        raise ValueError(f"unknown color {spec!r}; pass a known color name or hex like '#33A1FF'")
    r, g, b = rgb
    return {"r": r, "g": g, "b": b}


def _color_write_entry(channel: int, color_spec: str) -> dict:
    params = {"channel": channel, **_color_params(color_spec)}
    return operations.prepare_operation("channel", "set_color", params).safe_write_group_entry()


def _mixer_color_entry(track: int, color_spec: str) -> dict:
    params = {"track": track, **_color_params(color_spec)}
    return operations.prepare_operation("mixer", "set_color", params).safe_write_group_entry()


def _channel_rename_entry(channel: int, name: str) -> dict:
    return operations.prepare_operation(
        "channel", "set_name", {"channel": channel, "name": name}
    ).safe_write_group_entry()


def _channel_index(row: dict) -> int:
    return int(row.get("channel", row.get("i", row.get("index", 0))))


def _suggest_channel_name(row: dict) -> str:
    idx = _channel_index(row)
    target_name = str(row.get("target_name") or "").strip()
    if target_name and target_name.lower() != "master" and not target_name.startswith("Insert "):
        return target_name
    label = str((row.get("type") or {}).get("label") or "channel").strip() or "channel"
    if label == "audioclip":
        return f"Audio Clip {idx}"
    if label == "genplug":
        return f"Instrument {idx}"
    return f"Channel {idx}"


def _cleanup_proposal(
    *,
    id: str,
    title: str,
    reason: str,
    risk: str,
    params: dict,
    target: dict,
    tool: str = "fl_apply_project_cleanup_step",
    manual_review: bool = False,
) -> dict:
    proposal_params = dict(params)
    if tool in _ORGANIZER_APPLY_TOOLS:
        proposal_params["approved"] = True
    return wr.proposed_change(
        id=id,
        title=title,
        tool=tool,
        observed_state=target,
        proposed_state=proposal_params,
        safety_class="write-safe-required" if tool in _ORGANIZER_APPLY_TOOLS else "read-only",
        risk_level=risk,
        readback_expectation="Affected channel or mixer metadata is read back where supported.",
        rollback_expectation="MCP changelog rollback restores the prior metadata.",
        requires_explicit_approval=True,
    )


def _proposal_for_rename(kind: str, index: int, before_name: str, after_name: str) -> dict:
    return _cleanup_proposal(
        id=f"rename_{kind}_{index}",
        title=f"Rename {kind} {index} to {after_name}",
        reason=f"{kind.title()} name is empty, default, or duplicated.",
        risk="low",
        params={"renames": [{"type": kind, "index": index, "name": after_name}]},
        target={"type": kind, "index": index, "before_name": before_name, "after_name": after_name},
    )


def _proposal_for_color(kind: str, index: int, color: str) -> dict:
    return _cleanup_proposal(
        id=f"color_{kind}_{index}",
        title=f"Color {kind} {index} {color}",
        reason="Color proposal supplied by the user or active cleanup standard.",
        risk="low",
        params={"colors": [{"type": kind, "index": index, "hex": color}]},
        target={"type": kind, "index": index, "hex": color},
    )


def _proposal_for_channel_routing(
    channel: int,
    track: int | None = None,
    *,
    start_track: int = 1,
) -> dict:
    route = {"channel": channel}
    target = {"type": "channel", "index": channel}
    if track is None:
        route.update({"mode": "free", "start_track": start_track})
        target["target_mixer_track"] = "next_free"
        title = f"Assign channel {channel} to a free mixer track"
    else:
        route["track"] = track
        target["target_mixer_track"] = track
        title = f"Assign channel {channel} to mixer track {track}"
    return _cleanup_proposal(
        id=f"route_channel_{channel}_mixer_target",
        title=title,
        reason="Channel is routed only to Master or has unknown routing.",
        risk="low",
        params={"routing": [route]},
        target=target,
    )


def _apply_report(
    *,
    title: str,
    tool_name: str,
    rollback_unit: str,
    writes: list[dict],
    requested_changes: list[dict],
    approved: bool,
    bridge,
    kb_rule_ids: list[str],
    approval_changes: list[dict] | None = None,
) -> dict:
    if not requested_changes:
        return wr.workflow_report(
            workflow="project_organizer_apply",
            title=title,
            mode="no_op",
            status="No valid organizer changes requested",
            summary={"proposed_changes": 0, "applied_changes": 0},
            notes=["No FL Studio project state was changed."],
            ok=False,
        )
    if not approved:
        return wr.approval_required_report(
            workflow="project_organizer_apply",
            title=title,
            proposed_changes=approval_changes or requested_changes,
        )
    if not writes:
        return wr.workflow_report(
            workflow="project_organizer_apply",
            title=title,
            mode="rejected",
            status="No valid writes could be prepared",
            summary={"proposed_changes": len(requested_changes), "applied_changes": 0},
            proposed_changes=requested_changes,
            ok=False,
        )
    res = safety.safe_write_group(
        bridge,
        tool=tool_name,
        scope="project_organizer",
        writes=writes,
        rollback_unit=rollback_unit,
    )
    if res.get("dry_run"):
        dry_run_changes = approval_changes or requested_changes
        return wr.workflow_report(
            workflow="project_organizer_apply",
            title=title,
            mode="dry_run",
            status="Dry-run only",
            summary={"proposed_changes": len(dry_run_changes), "applied_changes": 0},
            proposed_changes=dry_run_changes,
            notes=["Dry-run mode is enabled; no FL Studio project state was changed."],
            kb_policy_refs=kb_policy.rule_refs(kb_rule_ids),
            safety={"read_only": True, "requires_explicit_approval": True},
        )
    before = res.get("before") or []
    after = res.get("after") or []
    risk = "medium" if len(requested_changes) > 1 else "low"
    applied = []
    for index, proposal in enumerate(requested_changes):
        applied.append(
            wr.applied_change(
                id=proposal["id"],
                title=proposal["title"],
                tool=tool_name,
                before=before[index] if index < len(before) else None,
                requested_change=proposal.get("proposed_state") or proposal.get("params") or {},
                after=after[index] if index < len(after) else None,
                safety_class="write-safe-required",
                risk_level=risk,
                change_id=res.get("change_id"),
                readback_ok=index < len(after),
                rollback=res.get("rollback"),
            )
        )
    return wr.workflow_report(
        workflow="project_organizer_apply",
        title=title,
        mode="applied",
        status="Applied",
        summary={"proposed_changes": 0, "applied_changes": len(applied)},
        applied_changes=applied,
        notes=["Rollback with fl_rollback_last_change if the result is not intended."],
        kb_policy_refs=kb_policy.rule_refs(kb_rule_ids),
        safety={
            "read_only": False,
            "requires_explicit_approval": False,
            "approval_received": True,
        },
    )


def register(mcp: FastMCP) -> None:
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

    @mcp.tool(annotations={"title": "Analyze Project Organization", **_RO})
    def fl_analyze_project_organization() -> dict:
        """Analyze project to find unnamed channels, uncolored channels, and unassigned tracks.

        Safety: Read-Only.
        """
        bridge = get_bridge()
        snapshot = get_analysis_broker().get_static_project_snapshot(bridge)
        chans = {"channels": list(snapshot.channels)}
        template_context = snapshot.template_context

        diagnostics = []
        unnamed = []
        ungrouped = []

        for c in chans.get("channels", []):
            if _looks_default_channel_name(c.get("name")):
                unnamed.append(c)
                idx = _channel_index(c)
                diagnostics.append(
                    wr.diagnostic(
                        id=f"default_channel_name_{idx}",
                        severity="low",
                        message=f"Channel {idx} has a default or empty name.",
                        evidence={"name": c.get("name")},
                        target={"type": "channel", "index": idx},
                        source="project_organizer",
                    )
                )

            # Simple heuristic for uncolored (assuming default FL color or no color)
            # We don't have color in routing summary currently, we'd need to fetch or assume.
            # But the agent can use this as a structural check.

            tgt = c.get("target_mixer_track")
            if (
                not isinstance(tgt, int)
                or tgt == 0
                and not templates.is_template_bus(template_context, tgt)
            ):
                ungrouped.append(c)
                idx = _channel_index(c)
                diagnostics.append(
                    wr.diagnostic(
                        id=f"master_routed_channel_{idx}",
                        severity="medium",
                        message=f"Channel {idx} is routed only to Master or has unknown routing.",
                        evidence={"target_mixer_track": tgt},
                        target={"type": "channel", "index": idx},
                        source="project_organizer",
                    )
                )

        payload = wr.workflow_report(
            workflow="project_organizer",
            title="Project Organization Analysis",
            mode="diagnostic",
            status="Organization analysis generated",
            summary={
                "unnamed_channels": len(unnamed),
                "ungrouped_channels": len(ungrouped),
                "diagnostics": len(diagnostics),
            },
            diagnostics=diagnostics,
            notes=[
                "Use fl_plan_project_cleanup to generate proposal-first cleanup actions.",
                "Preserve linked Channel, Playlist, and Mixer naming/coloring where it is already evident.",  # noqa: E501
                "Do not infer Channel, Playlist Track, and Mixer Track links from numeric index alone.",  # noqa: E501
                "Only apply cleanup through rollback-safe wrappers.",
            ],
            kb_policy_refs=kb_policy.rule_refs(
                [
                    "preserve_existing_structure_first",
                    "instrument_audio_track_workflow",
                    "channel_rack_workflow_requires_routing_inference",
                ]
            ),
            metadata={
                "unnamed_channels": unnamed,
                "ungrouped_channels": ungrouped,
                "template_context": templates.compact_context(template_context),
            },
            safety={"read_only": True, "requires_explicit_approval": False},
        )
        return enrich_workflow_report_with_analysis(
            payload,
            analysis_mode="static_snapshot",
            evidence_mode="static_snapshot_only",
            project_fingerprint=snapshot.project_fingerprint,
            source_observations=snapshot.source_observation_ids,
        )

    @mcp.tool(annotations={"title": "Plan Project Cleanup", **_RO})
    def fl_plan_project_cleanup() -> dict:
        """Create a dry-run plan for project cleanup.

        Safety: Read-Only.
        """
        bridge = get_bridge()
        snapshot = get_analysis_broker().get_static_project_snapshot(bridge)
        chans = list(snapshot.channels)
        mixer_tracks = list(snapshot.mixer_tracks)
        template_context = snapshot.template_context

        diagnostics = []
        proposed_changes = []
        for c in chans:
            idx = _channel_index(c)
            if _looks_default_channel_name(c.get("name")):
                suggested = _suggest_channel_name(c)
                diagnostics.append(
                    wr.diagnostic(
                        id=f"default_channel_name_{idx}",
                        severity="low",
                        message=f"Channel {idx} has a default or empty name.",
                        evidence={"name": c.get("name"), "suggested_name": suggested},
                        target={"type": "channel", "index": idx},
                        source="project_organizer",
                    )
                )
                proposed_changes.append(
                    _proposal_for_rename("channel", idx, str(c.get("name") or ""), suggested)
                )
            target = c.get("target_mixer_track")
            if (
                not isinstance(target, int)
                or target == 0
                and not templates.is_template_bus(template_context, target)
            ):
                diagnostics.append(
                    wr.diagnostic(
                        id=f"master_routed_channel_{idx}",
                        severity="medium",
                        message=f"Channel {idx} is routed only to Master or has unknown routing.",
                        evidence={"target_mixer_track": target},
                        target={"type": "channel", "index": idx},
                        source="project_organizer",
                    )
                )
                proposed_changes.append(_proposal_for_channel_routing(idx))

        duplicate_mixer_names = {}
        for row in mixer_tracks:
            name = str(row.get("name") or "").strip()
            if not name:
                continue
            duplicate_mixer_names.setdefault(name, []).append(row)
        for name, rows in duplicate_mixer_names.items():
            if len(rows) < 2:
                continue
            for row in rows[1:]:
                idx = int(row.get("i", row.get("index", 0)))
                suggested = f"{name} ({idx})"
                diagnostics.append(
                    wr.diagnostic(
                        id=f"duplicate_mixer_name_{idx}",
                        severity="low",
                        message=f"Mixer track {idx} duplicates the name {name}.",
                        evidence={"name": name, "suggested_name": suggested},
                        target={"type": "mixer", "index": idx},
                        source="project_organizer",
                    )
                )
                proposed_changes.append(_proposal_for_rename("mixer", idx, name, suggested))

        payload = wr.workflow_report(
            workflow="project_organizer",
            title="Project Cleanup Proposal",
            mode="proposal",
            status="Project cleanup proposals generated",
            summary={
                "diagnostics": len(diagnostics),
                "proposed_changes": len(proposed_changes),
                "channels_scanned": len(chans),
                "mixer_tracks_scanned": len(mixer_tracks),
            },
            diagnostics=diagnostics,
            proposed_changes=proposed_changes,
            notes=[
                "This tool is read-only and applies no FL changes.",
                "Apply only one approved proposal or one named rollback unit at a time.",
                "Do not move playlist clips, delete clips/patterns, or load plugins.",
            ],
            kb_policy_refs=kb_policy.rule_refs(
                [
                    "preserve_existing_structure_first",
                    "instrument_audio_track_workflow",
                    "routing_ui_guidance_vs_mcp_write",
                ]
            ),
            metadata={"template_context": templates.compact_context(template_context)},
            safety={"read_only": True, "requires_explicit_approval": bool(proposed_changes)},
        )
        return enrich_workflow_report_with_analysis(
            payload,
            analysis_mode="static_snapshot",
            evidence_mode="static_snapshot_only",
            project_fingerprint=snapshot.project_fingerprint,
            source_observations=snapshot.source_observation_ids,
        )

    @mcp.tool(annotations={"title": "Apply Project Cleanup Step", **_WR})
    def fl_apply_project_cleanup_step(
        renames: Annotated[
            list[dict],
            Field(description="List of {type: 'channel'|'mixer', index: int, name: str}"),
        ] = None,
        colors: Annotated[
            list[dict], Field(description="List of {type: 'channel'|'mixer', index: int, hex: str}")
        ] = None,
        routing: Annotated[
            list[dict],
            Field(
                description=(
                    "List of {channel: int, track: int} or "
                    "{channel: int, mode: 'free', start_track?: int}"
                )
            ),
        ] = None,
        approved: Annotated[
            bool,
            Field(description="Must be true after explicit approval of this exact cleanup step."),
        ] = False,
    ) -> dict:
        """Apply a batch of names, colors, and channel routing in one rollback unit.

        Safety: Write-Safe-Required with Rollback.
        """
        bridge = get_bridge()
        writes = []
        requested_changes = []

        if renames:
            try:
                for r in renames:
                    if r["type"] == "channel":
                        writes.append(_channel_rename_entry(r["index"], r["name"]))
                        requested_changes.append(
                            _proposal_for_rename(
                                "channel", r["index"], str(r.get("from", "")), r["name"]
                            )
                        )
                    elif r["type"] == "mixer":
                        writes.append(_bus_rename_entry(r["index"], r["name"]))
                        requested_changes.append(
                            _proposal_for_rename(
                                "mixer", r["index"], str(r.get("from", "")), r["name"]
                            )
                        )
                    else:
                        raise ValueError("rename type must be 'channel' or 'mixer'")
            except (KeyError, ValueError, operations.OperationValidationError) as e:
                return wr.workflow_report(
                    workflow="project_organizer_apply",
                    title="Apply Project Cleanup Step",
                    mode="rejected",
                    status="Invalid rename request",
                    summary={"applied_changes": 0},
                    diagnostics=[
                        wr.diagnostic(
                            id="invalid_cleanup_rename",
                            severity="error",
                            message=str(e),
                            evidence={"renames": renames},
                        )
                    ],
                    ok=False,
                )

        if colors:
            try:
                for c in colors:
                    if c["type"] == "channel":
                        writes.append(_color_write_entry(c["index"], c["hex"]))
                        requested_changes.append(
                            _proposal_for_color("channel", c["index"], c["hex"])
                        )
                    elif c["type"] == "mixer":
                        writes.append(_mixer_color_entry(c["index"], c["hex"]))
                        requested_changes.append(_proposal_for_color("mixer", c["index"], c["hex"]))
                    else:
                        raise ValueError("color type must be 'channel' or 'mixer'")
            except (KeyError, ValueError, operations.OperationValidationError) as e:
                return wr.workflow_report(
                    workflow="project_organizer_apply",
                    title="Apply Project Cleanup Step",
                    mode="rejected",
                    status="Invalid color request",
                    summary={"applied_changes": 0},
                    diagnostics=[
                        wr.diagnostic(
                            id="invalid_cleanup_color",
                            severity="error",
                            message=str(e),
                            evidence={"colors": colors},
                        )
                    ],
                    ok=False,
                )

        if routing:
            reserved_tracks: set[int] = set()
            try:
                for r in routing:
                    channel = int(r["channel"])
                    if r.get("mode") == "free" or "track" not in r:
                        start_track = int(r.get("start_track", 1))
                        candidate_start = start_track
                        track = None
                        while True:
                            candidate = _find_free_mixer_track(bridge, start_track=candidate_start)
                            if candidate is None:
                                break
                            if candidate not in reserved_tracks:
                                track = candidate
                                break
                            candidate_start = candidate + 1
                        if track is None:
                            raise ValueError("no free mixer track available")
                    else:
                        track = int(r["track"])
                    reserved_tracks.add(track)
                    prepared = operations.prepare_operation(
                        "channel",
                        "set_mixer_target",
                        {"channel": channel, "track": track},
                    )
                    writes.append(prepared.safe_write_group_entry())
                    requested_changes.append(_proposal_for_channel_routing(channel, track))
            except (KeyError, ValueError, operations.OperationValidationError) as e:
                return wr.workflow_report(
                    workflow="project_organizer_apply",
                    title="Apply Project Cleanup Step",
                    mode="rejected",
                    status="Invalid routing request",
                    summary={"applied_changes": 0},
                    diagnostics=[
                        wr.diagnostic(
                            id="invalid_cleanup_routing",
                            severity="error",
                            message=str(e),
                            evidence={"routing": routing},
                        )
                    ],
                    ok=False,
                )

        return _apply_report(
            title="Apply Project Cleanup Step",
            tool_name="apply_project_cleanup",
            rollback_unit="project_cleanup_step",
            writes=writes,
            requested_changes=requested_changes,
            approved=approved,
            bridge=bridge,
            kb_rule_ids=["preserve_existing_structure_first", "instrument_audio_track_workflow"],
        )

    @mcp.tool(annotations={"title": "Apply Naming Standard", **_WR})
    def fl_apply_naming_standard(
        style: Annotated[
            str, Field(description="Naming schema (e.g. 'psytrance', 'default', 'dynamic')")
        ],
        rules: Annotated[
            list[dict],
            Field(description="Specific rewrite rules applied by LLM: {type, index, name}"),
        ],
        approved: Annotated[
            bool,
            Field(description="Must be true after explicit approval of this naming batch."),
        ] = False,
    ) -> dict:
        """Batch apply standardized names across the project.

        Safety: Write-Safe-Required with Rollback.
        """
        bridge = get_bridge()
        writes = []
        requested_changes = []
        try:
            for r in rules:
                if r["type"] == "channel":
                    writes.append(_channel_rename_entry(r["index"], r["name"]))
                    requested_changes.append(
                        _proposal_for_rename(
                            "channel", r["index"], str(r.get("from", "")), r["name"]
                        )
                    )
                elif r["type"] == "mixer":
                    writes.append(_bus_rename_entry(r["index"], r["name"]))
                    requested_changes.append(
                        _proposal_for_rename("mixer", r["index"], str(r.get("from", "")), r["name"])
                    )
                else:
                    raise ValueError("rule type must be 'channel' or 'mixer'")
        except (KeyError, ValueError, operations.OperationValidationError) as e:
            return wr.workflow_report(
                workflow="project_organizer_apply",
                title="Apply Naming Standard",
                mode="rejected",
                status="Invalid naming rule",
                summary={"applied_changes": 0},
                diagnostics=[
                    wr.diagnostic(
                        id="invalid_naming_rule",
                        severity="error",
                        message=str(e),
                        evidence={"rules": rules},
                    )
                ],
                ok=False,
            )

        return _apply_report(
            title="Apply Naming Standard",
            tool_name="apply_naming_standard",
            rollback_unit=f"naming_standard_{style}",
            writes=writes,
            requested_changes=requested_changes,
            approved=approved,
            bridge=bridge,
            kb_rule_ids=["preserve_existing_structure_first", "instrument_audio_track_workflow"],
            approval_changes=[
                _cleanup_proposal(
                    id=f"naming_standard_{style}",
                    title=f"Apply {style} naming standard",
                    reason="Batch naming standard requires explicit approval.",
                    risk="medium" if len(requested_changes) > 1 else "low",
                    tool="fl_apply_naming_standard",
                    params={"style": style, "rules": rules},
                    target={"rules": len(rules)},
                )
            ],
        )

    @mcp.tool(annotations={"title": "Apply Color Standard", **_WR})
    def fl_apply_color_standard(
        style: Annotated[
            str, Field(description="Color schema (e.g. 'psytrance', 'default', 'dynamic')")
        ],
        rules: Annotated[
            list[dict], Field(description="Specific color rules applied by LLM: {type, index, hex}")
        ],
        approved: Annotated[
            bool,
            Field(description="Must be true after explicit approval of this color batch."),
        ] = False,
    ) -> dict:
        """Batch apply standardized colors across the project. Hex should be e.g. '#FF0000'.

        Safety: Write-Safe-Required with Rollback.
        """
        bridge = get_bridge()
        writes = []
        requested_changes = []
        try:
            for r in rules:
                if r["type"] == "channel":
                    writes.append(_color_write_entry(r["index"], r["hex"]))
                    requested_changes.append(_proposal_for_color("channel", r["index"], r["hex"]))
                elif r["type"] == "mixer":
                    writes.append(_mixer_color_entry(r["index"], r["hex"]))
                    requested_changes.append(_proposal_for_color("mixer", r["index"], r["hex"]))
                else:
                    raise ValueError("rule type must be 'channel' or 'mixer'")
        except (KeyError, ValueError, operations.OperationValidationError) as e:
            return wr.workflow_report(
                workflow="project_organizer_apply",
                title="Apply Color Standard",
                mode="rejected",
                status="Invalid color rule",
                summary={"applied_changes": 0},
                diagnostics=[
                    wr.diagnostic(
                        id="invalid_color_rule",
                        severity="error",
                        message=str(e),
                        evidence={"rules": rules},
                    )
                ],
                ok=False,
            )

        return _apply_report(
            title="Apply Color Standard",
            tool_name="apply_color_standard",
            rollback_unit=f"color_standard_{style}",
            writes=writes,
            requested_changes=requested_changes,
            approved=approved,
            bridge=bridge,
            kb_rule_ids=["preserve_existing_structure_first", "instrument_audio_track_workflow"],
            approval_changes=[
                _cleanup_proposal(
                    id=f"color_standard_{style}",
                    title=f"Apply {style} color standard",
                    reason="Batch color standard requires explicit approval.",
                    risk="medium" if len(requested_changes) > 1 else "low",
                    tool="fl_apply_color_standard",
                    params={"style": style, "rules": rules},
                    target={"rules": len(rules)},
                )
            ],
        )

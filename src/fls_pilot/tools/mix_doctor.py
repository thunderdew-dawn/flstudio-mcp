"""MCP tools for Mix Review: diagnose the whole mix + apply gated adjustments.

fl_review_mix is READ-ONLY (thin paginated snapshot + transparent threshold
diagnosis). fl_apply_mix_adjustment applies ONE proposed adjustment through the safety layer
(snapshot -> write -> FRESH readback -> rollback-able). Diagnosis never writes;
apply is a separate explicit call so the human approves each adjustment in conversation.

Grouping and EQ moves are surfaced as proposals but applied via the existing
fl_group_tracks / fl_apply_eq_intent tools (reuse, not re-implement).
"""

from __future__ import annotations

import math
from typing import Annotated

from fastmcp import FastMCP
from pydantic import Field

from .. import kb_policy, operations, protocol, safety
from .. import workflow_report as wr
from ..analysis import (
    StaticSnapshotPolicy,
    get_analysis_broker,
)
from ..analysis.live import LiveMeterPolicy
from ..connection import fetch_all_pages, get_bridge
from ..music import mix_doctor as md
from ..music.mix_review_levels import (
    MixReviewLevel,
    allow_inline_live_meter,
    normalize_mix_review_options,
)
from ..project_templates import compact_context


def _gather_analysis_snapshot(bridge, *, with_params: bool = True, options=None) -> dict:
    mix_options = normalize_mix_review_options(options) if options is not None else None
    broker = get_analysis_broker()
    static_snapshot = broker.get_static_project_snapshot(
        bridge,
        StaticSnapshotPolicy(),
    )
    watcher = md.get_watcher()
    live_window = None
    if mix_options is None:
        live_window = broker.get_live_meter_window(
            bridge,
            policy=LiveMeterPolicy(require_playing=False, min_capture_seconds=30.0),
            watcher_provider=watcher,
            static_snapshot=static_snapshot,
        )
    elif mix_options.level == MixReviewLevel.LIVE_WATCH:
        live_window = broker.get_live_meter_window(
            bridge,
            policy=LiveMeterPolicy(
                require_playing=False,
                min_capture_seconds=float(mix_options.capture.loop_seconds),
            ),
            watcher_provider=watcher,
            static_snapshot=static_snapshot,
        )
    watch_peaks = (
        {
            int(track): peak
            for track, peak in live_window.track_meter_summaries.items()
        }
        if live_window and live_window.freshness == "fresh"
        else None
    )
    snap = md.gather_snapshot(
        bridge,
        with_params=with_params,
        peaks_override=watch_peaks or None,
        live_window=live_window,
        static_snapshot=static_snapshot,
        allow_live_meter=allow_inline_live_meter(mix_options),
    )
    if mix_options is not None:
        snap["mix_review_options"] = mix_options.to_dict()
    return snap


def _compact_kb_fields(row: dict) -> dict:
    """Compact KB metadata for per-finding/proposal tool output."""
    rule_ids = [str(rule_id) for rule_id in (row.get("kb_rule_ids") or []) if rule_id]
    if not rule_ids:
        return {}
    out = {"kb_rule_ids": rule_ids}
    confidence = {}
    for rule_id in rule_ids:
        ref = kb_policy.rule_ref(rule_id)
        level = ref.get("confidence_level")
        if level is not None:
            confidence[rule_id] = level
    if confidence:
        out["kb_confidence_levels"] = confidence
    if row.get("safety_limits"):
        out["safety_limits"] = row["safety_limits"]
    return out


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
        "idempotentHint": False,
        "openWorldHint": True,
        "safetyClass": "write-safe-required",
    }

    def _diagnostic_from_finding(finding: dict, *, index: int, source: str) -> dict:
        track = finding.get("track")
        target = {"track_name": track}
        if isinstance(track, int):
            target = {"track": track}
        metadata = {
            key: value
            for key, value in _compact_kb_fields(finding).items()
            if key not in {"kb_rule_ids"}
        }
        for key in (
            "evidence_type",
            "proof_status",
            "confidence",
            "requires_audio_evidence_for_confirmation",
            "mix_review_level",
        ):
            if key in finding:
                metadata[key] = finding[key]
        return wr.diagnostic(
            id=f"{finding.get('rule', 'finding')}_{index}",
            severity=finding.get("severity", "info"),
            message=finding.get("message", ""),
            evidence=finding.get("evidence"),
            target=target,
            source=source,
            kb_rule_ids=finding.get("kb_rule_ids") or [],
            metadata=metadata,
        )

    def _risk_for_plan(plan: dict) -> str:
        if plan.get("kind") == "trim_volume":
            return "low"
        if plan.get("kind") == "group":
            return "read-only"
        return "medium" if plan.get("actionable") else "unsupported"

    def _proposal_from_plan(plan: dict, *, index: int, source: str) -> dict:
        kind = plan.get("kind", "change")
        if kind == "trim_volume":
            tool = "fl_apply_mix_adjustment"
            proposed_state = {
                "kind": "trim_volume",
                "track": plan.get("track"),
                "target_db": plan.get("target_fader_db"),
                "approved": True,
            }
            observed_state = {"track": plan.get("track"), "track_name": plan.get("track_name")}
            readback = "Mixer track fader dB is read back after the write."
            rollback = "MCP changelog restores the prior mixer track volume."
            safety_class = "write-safe-required"
        elif kind == "group":
            tool = "fl_plan_routing_cleanup"
            proposed_state = {
                "issues": [plan.get("reason") or plan.get("human") or "grouping review"],
                "proposed_buses": [],
            }
            observed_state = {"tracks": plan.get("args") or []}
            readback = "Read-only routing plan; no FL write is performed."
            rollback = "No rollback needed for read-only routing planning."
            safety_class = "read-only"
        else:
            tool = plan.get("tool") or str(kind)
            proposed_state = plan.get("params") or {}
            observed_state = {}
            readback = "Readback depends on the selected write-safe tool."
            rollback = "Rollback depends on the selected write-safe tool."
            safety_class = "read-only"

        row = wr.proposed_change(
            id=f"{source}_proposal_{index}",
            title=plan.get("human") or f"{kind} proposal",
            tool=tool,
            observed_state=observed_state,
            proposed_state=proposed_state,
            safety_class=safety_class,
            risk_level=_risk_for_plan(plan),
            readback_expectation=readback,
            rollback_expectation=rollback,
            requires_explicit_approval=kind != "group",
        )
        if plan.get("kb_rule_ids"):
            row["kb_rule_ids"] = plan.get("kb_rule_ids")
        kb_meta = {
            key: value
            for key, value in _compact_kb_fields(plan).items()
            if key not in {"kb_rule_ids"}
        }
        if kb_meta:
            row["metadata"] = kb_meta
        return row

    def _proposal_from_finding(finding: dict, *, index: int, source: str) -> dict | None:
        fix = finding.get("proposed_fix") or {}
        intent = fix.get("intent")
        if not intent:
            return None
        manual = intent in {"manual_review", "user_action_required"}
        risk = "read-only" if manual else "low"
        if intent in {"fl_apply_eq_intent", "fl_group_tracks"}:
            risk = "medium"
        if intent == "user_action_required":
            risk = "unsupported"

        tool = "manual_review" if manual else intent
        proposed_state = fix.get("args") or {}
        observed_state = {"track_name": finding.get("track")}
        safety_class = "read-only" if manual else "write-safe-required"

        row = wr.proposed_change(
            id=f"{source}_proposal_{index}",
            title=fix.get("desc") or finding.get("message") or "Review finding",
            tool=tool,
            observed_state=observed_state,
            proposed_state=proposed_state,
            safety_class=safety_class,
            risk_level=risk,
            readback_expectation=(
                "Manual check; no FL write readback."
                if manual
                else "Readback depends on the referenced write-safe tool."
            ),
            rollback_expectation=(
                "No project write is performed by this proposal."
                if manual
                else "Rollback is provided by the referenced write-safe tool."
            ),
            requires_explicit_approval=not manual,
        )
        if finding.get("kb_rule_ids"):
            row["kb_rule_ids"] = finding.get("kb_rule_ids")
        kb_meta = {
            key: value
            for key, value in _compact_kb_fields(finding).items()
            if key not in {"kb_rule_ids"}
        }
        if kb_meta:
            row["metadata"] = kb_meta
        return row

    def _diagnostic_report(
        *,
        workflow: str,
        title: str,
        status: str,
        snap: dict,
        diagnostics: list[dict],
        proposed_changes: list[dict],
        notes: list[str],
        kb_rule_ids: set,
        summary: dict,
        metadata: dict | None = None,
        manual_checks: list[dict] | None = None,
        limits: list[str] | None = None,
    ) -> dict:
        payload = wr.workflow_report(
            workflow=workflow,
            title=title,
            mode="proposal" if proposed_changes and not diagnostics else "diagnostic",
            status=status,
            summary=summary,
            diagnostics=diagnostics,
            proposed_changes=proposed_changes,
            manual_checks=manual_checks or [],
            notes=notes,
            limits=limits or [],
            kb_policy_refs=kb_policy.rule_refs(sorted(kb_rule_ids)),
            safety={
                "read_only": True,
                "requires_explicit_approval": bool(proposed_changes),
                "approval_received": False,
            },
            metadata={
                "track_count": snap.get("track_count"),
                "levels_valid": snap.get("levels_valid"),
                "template_context": compact_context(snap.get("template_context") or {}),
                **(metadata or {}),
            },
        )
        peak_source = str(snap.get("peak_window", {}).get("source") or "")
        if peak_source == "watch":
            analysis_mode = "watch_window"
            evidence_mode = "sufficient_watch_window"
        elif snap.get("levels_valid"):
            analysis_mode = "live_runtime"
            evidence_mode = "short_live_snapshot"
        else:
            analysis_mode = "static_snapshot"
            evidence_mode = "static_snapshot_only"
        payload["analysis_mode"] = analysis_mode
        payload["evidence_mode"] = evidence_mode
        payload["project_fingerprint"] = snap.get("project_fingerprint") or "unknown"
        payload["source_observations"] = list(snap.get("source_observation_ids") or ())
        return payload

    def _mix_review_level_metadata(options, snap: dict) -> dict:
        peak_source = str((snap.get("peak_window") or {}).get("source") or "none")
        live_window = snap.get("live_window") if isinstance(snap.get("live_window"), dict) else {}
        watch_status = "available" if peak_source == "watch" else "missing"
        if live_window:
            freshness = str(live_window.get("freshness") or "")
            if freshness == "stale":
                watch_status = "stale"
            elif freshness == "partial":
                watch_status = "partial"
            elif freshness == "unavailable":
                watch_status = "missing"
        requested = options.requested_evidence_summary()
        rendered_master = requested["rendered_master"]
        rendered_stem_status = requested["rendered_stem_status"]
        return {
            "mix_review_level": int(options.level),
            "level_label": options.level_label,
            "genre_profile": options.genre_profile,
            "capture": options.capture.to_dict(),
            "evidence_summary": {
                "static_snapshot": "available",
                "live_meter": "available" if peak_source not in {"none", ""} else "missing",
                "watch_window": watch_status,
                "rendered_master": rendered_master.get("status", "missing"),
                "rendered_stems": rendered_stem_status,
            },
            "audio_evidence_requests": requested,
            "expected_checks": options.expected_checks(),
            "external_audio_analyzer": {
                "required_for_level_3_4": options.level >= MixReviewLevel.RENDERED_MASTER,
                "available": False,
                "status": "not_merged_yet",
            },
        }

    def _result(snap, options=None):
        """Diagnose + plan a gathered snapshot -> the common tool payload."""
        options = normalize_mix_review_options(options or snap.get("mix_review_options"))
        diag = md.diagnose(snap, mix_review_level=options.level)
        plan = md.plan_fixes(snap)
        proposed_changes = [
            _proposal_from_plan(p, index=index, source="mix_review")
            for index, p in enumerate(plan["plans"], start=1)
        ]
        diagnostics = []
        used_rule_ids = set()
        for index, f in enumerate(diag["findings"], start=1):
            row = _diagnostic_from_finding(f, index=index, source="mix_review")
            used_rule_ids.update(f.get("kb_rule_ids") or [])
            diagnostics.append(row)
        for p in proposed_changes:
            used_rule_ids.update(p.get("kb_rule_ids") or [])
        playing = snap.get("playing")
        peak_source = str((snap.get("peak_window") or {}).get("source") or "")
        needs_level_2_watch = (
            options.level == MixReviewLevel.LIVE_WATCH
            and snap.get("peak_window", {}).get("source") != "watch"
        )
        guidance = (
            "Current mixer peaks were collected because FL Studio playback was running. "
            "Treat them as momentary live evidence, not a full-song watch window."
            if options.level == MixReviewLevel.STATIC
            and snap.get("levels_valid")
            and peak_source not in {"", "none", "watch"}
            else "This is a static project/mixer review. Audio-dependent checks require "
            "playback, Level 2 watch, Level 3, or Level 4 evidence."
            if options.level == MixReviewLevel.STATIC
            else "Current mixer peaks were collected for this run. Start Level 2 Watch "
            "at the loudest section when you need bounded loud-section evidence."
            if needs_level_2_watch and snap.get("levels_valid")
            else "Start Level 2 Watch at the loudest section for 8-60 seconds, then "
            "run Mix Review again."
            if needs_level_2_watch
            else "Rendered/stem evidence is prepared, but audio feature analysis is "
            "pending the external analyzer integration."
            if options.level >= MixReviewLevel.RENDERED_MASTER
            else "Short snapshot only; use watch mode for full-song peak evidence."
        )
        level_metadata = _mix_review_level_metadata(options, snap)
        return _diagnostic_report(
            workflow="mix_review",
            title="Mix Review",
            status=(
                "Needs Level 2 Watch"
                if needs_level_2_watch and not snap.get("levels_valid")
                else "Mix review generated"
            ),
            snap={**snap, "template_context": diag.get("template_context")},
            diagnostics=diagnostics,
            proposed_changes=proposed_changes,
            notes=[guidance, *plan["notes"]],
            kb_rule_ids=used_rule_ids,
            summary=plan["summary"],
            metadata={
                "playing": playing,
                "needs_playback": needs_level_2_watch and not snap.get("levels_valid"),
                "peak_source": snap.get("peak_window", {}).get("source"),
                **level_metadata,
            },
        )

    def _low_end_stereo_result(snap):
        report = md.low_end_stereo_safety(snap)
        diagnostics = []
        manual_checks = []
        proposed_changes = []
        used_rule_ids = set()
        for index, f in enumerate(report["findings"], start=1):
            row = _diagnostic_from_finding(f, index=index, source="low_end_stereo")
            used_rule_ids.update(f.get("kb_rule_ids") or [])
            diagnostics.append(row)
            proposal = _proposal_from_finding(f, index=index, source="low_end_stereo")
            if proposal:
                proposed_changes.append(proposal)
        for index, check in enumerate(report["manual_checks"], start=1):
            row = {
                "id": f"low_end_manual_check_{index}",
                "topic": check.get("topic"),
                "check": check.get("check"),
                "reason": check.get("reason"),
            }
            row.update(
                {
                    key: value
                    for key, value in _compact_kb_fields(check).items()
                    if key not in {"kb_rule_ids"}
                }
            )
            if check.get("kb_rule_ids"):
                row["kb_rule_ids"] = check.get("kb_rule_ids")
            used_rule_ids.update(check.get("kb_rule_ids") or [])
            manual_checks.append(row)
        return _diagnostic_report(
            workflow="low_end_stereo_review",
            title="Low-End and Stereo Safety Review",
            status="Low-end/stereo review generated",
            snap={
                "track_count": report.get("track_count"),
                "levels_valid": report.get("levels_valid"),
                "template_context": report.get("template_context") or {},
            },
            diagnostics=diagnostics,
            proposed_changes=proposed_changes,
            manual_checks=manual_checks,
            notes=report["notes"],
            limits=report["analysis_limits"],
            kb_rule_ids=used_rule_ids,
            summary=report["summary"],
            metadata={"low_end_tracks": report.get("low_end_tracks", [])},
        )

    @mcp.tool(annotations={"title": "Review mix", **_RO})
    def fl_review_mix(
        level: Annotated[
            int | str | None,
            Field(description="Mix Review level 1..4. Defaults to Level 1 static."),
        ] = None,
        genre_profile: Annotated[
            str | None,
            Field(description="Optional conservative genre/profile hint, e.g. psytrance."),
        ] = None,
        loop_seconds: Annotated[
            int,
            Field(ge=8, le=60, description="Level 2 watch window length in seconds."),
        ] = 16,
        playback_mode: Annotated[
            str,
            Field(description="Level 2 playback choice: user_starts, gui_starts, or unknown."),
        ] = "unknown",
        marker_id: Annotated[
            str | None,
            Field(description="Optional marker id for the intended loud section."),
        ] = None,
        marker_name: Annotated[
            str | None,
            Field(description="Optional marker name for the intended loud section."),
        ] = None,
    ) -> dict:
        """Scan the WHOLE mix and report problems + proposed fixes. READ-ONLY.

        Level 1 is the default static review. Level 2 uses fresh peak-watch
        evidence when available. Level 3 and Level 4 prepare rendered-master or
        stem evidence metadata only; they do not run integrated loudness, true
        peak, spectrum, phase, masking, or stem audio analysis.

        Transparent threshold rules run on a thin paginated snapshot. Static
        heuristic findings are marked with evidence/proof/confidence metadata.
        Applies nothing.

        Safety: Read-Only.
        """
        options = normalize_mix_review_options(
            {
                "level": level if level is not None else 1,
                "genre_profile": genre_profile,
                "loop_seconds": loop_seconds,
                "playback_mode": playback_mode,
                "marker_id": marker_id,
                "marker_name": marker_name,
            }
        )
        try:
            snap = _gather_analysis_snapshot(get_bridge(), options=options)
        except Exception as e:
            return wr.workflow_report(
                workflow="mix_review",
                title="Mix Review",
                mode="error",
                status="Mix review failed",
                summary={"diagnostics": 0, "proposed_changes": 0},
                diagnostics=[
                    wr.diagnostic(
                        id="mix_review_error",
                        severity="error",
                        message=f"{type(e).__name__}: {e}",
                    )
                ],
                ok=False,
            )
        return _result(snap, options)

    @mcp.tool(annotations={"title": "Review low-end and stereo safety", **_RO})
    def fl_review_low_end_stereo() -> dict:
        """Report bass/sub mono compatibility, stereo-width risk, and Master
        headroom. READ-ONLY.

        Uses the same mixer snapshot path as Mix Review, plus mixer pan and
        stereo-separation metadata where the controller exposes it. This does
        not measure true phase correlation, mono-sum cancellation, or a spectral
        low band; those remain manual checks in the returned report.

        Safety: Read-Only.
        """
        try:
            bridge = get_bridge()
            snap = _gather_analysis_snapshot(bridge, with_params=False)
        except Exception as e:
            return wr.workflow_report(
                workflow="low_end_stereo_review",
                title="Low-End and Stereo Safety Review",
                mode="error",
                status="Low-end/stereo review failed",
                summary={"diagnostics": 0, "proposed_changes": 0},
                diagnostics=[
                    wr.diagnostic(
                        id="low_end_stereo_error",
                        severity="error",
                        message=f"{type(e).__name__}: {e}",
                    )
                ],
                ok=False,
            )
        levels_valid = bool(snap.get("levels_valid"))
        guidance = (
            "Structural pan/stereo checks are available. For reliable hot low-end "
            "and Master-headroom evidence, press PLAY or use watch mode "
            "(fl_mix_watch_start -> play -> fl_mix_watch_stop)."
            if not levels_valid
            else "Read-only report. Treat stereo/phase items as manual checks; "
            "apply no widening, mid-side EQ, mastering, render, or plugin-loading "
            "automation from this assistant."
        )
        report = _low_end_stereo_result(snap)
        report["notes"] = [guidance, *report.get("notes", [])]
        report["metadata"].update(
            {
                "playing": snap.get("playing"),
                "needs_levels": not levels_valid,
                "peak_source": "watch (full-song)"
                if snap.get("peak_window", {}).get("source") == "watch"
                else snap.get("peak_window", {}).get("source"),
            }
        )
        report["json_report"] = {
            key: value
            for key, value in report.items()
            if key not in {"json_report", "markdown_report"}
        }
        report["markdown_report"] = wr.render_markdown(report["json_report"])
        return report

    @mcp.tool(annotations={"title": "Apply mix adjustment (gated)", **_WR})
    def fl_apply_mix_adjustment(
        kind: Annotated[
            str, Field(description="Fix kind. Currently 'trim_volume' (the proven, safe one).")
        ],
        track: Annotated[
            int | None, Field(ge=0, description="Mixer track index (for trim_volume).")
        ] = None,
        target_db: Annotated[
            float | None, Field(description="Absolute target fader level in dB, e.g. -3.0.")
        ] = None,
        approved: Annotated[
            bool,
            Field(description="Must be true after explicit approval of this exact change."),
        ] = False,
    ) -> dict:
        """Apply ONE Mix Review adjustment via the safety layer: snapshot -> write ->
        FRESH readback -> rollback-able with fl_rollback_last_change.

        Call this ONLY after the user approves the exact change in conversation
        (Mix Review never auto-applies). 'trim_volume' sets a mixer track's fader
        to target_db. For grouping use fl_group_tracks; for EQ use
        fl_apply_eq_intent.

        Safety: Write-Safe-Required with Rollback.
        """
        if kind != "trim_volume":
            return wr.workflow_report(
                workflow="mix_review_apply",
                title="Apply Mix Review Adjustment",
                mode="rejected",
                status="Unsupported mix adjustment",
                summary={"applied_changes": 0},
                diagnostics=[
                    wr.diagnostic(
                        id="unsupported_mix_adjustment",
                        severity="error",
                        message=(
                            "Only trim_volume is wired here; use fl_group_tracks "
                            "or fl_apply_eq_intent for other approved changes."
                        ),
                        evidence={"kind": kind},
                    )
                ],
                ok=False,
            )
        if track is None or target_db is None:
            return wr.workflow_report(
                workflow="mix_review_apply",
                title="Apply Mix Review Adjustment",
                mode="rejected",
                status="Missing parameters",
                summary={"applied_changes": 0},
                diagnostics=[
                    wr.diagnostic(
                        id="missing_trim_volume_params",
                        severity="error",
                        message="trim_volume needs both track and target_db.",
                        evidence={"track": track, "target_db": target_db},
                    )
                ],
                ok=False,
            )
        proposal = wr.proposed_change(
            id=f"mix_trim_track_{track}",
            title=f"Trim mixer track {track} to {target_db:.1f} dB",
            tool="fl_apply_mix_adjustment",
            observed_state={"track": track},
            proposed_state={"kind": kind, "track": track, "target_db": target_db, "approved": True},
            safety_class="write-safe-required",
            risk_level="low",
            readback_expectation="Mixer track fader dB is read back after write.",
            rollback_expectation="MCP changelog restores the prior mixer track volume.",
        )
        if not approved:
            return wr.approval_required_report(
                workflow="mix_review_apply",
                title="Apply Mix Review Adjustment",
                proposed_changes=[proposal],
            )
        try:
            bridge = get_bridge()
            prepared = operations.prepare_operation(
                "mixer", "set_volume", {"track": track, "value": target_db, "unit": "db"}
            )
            res = safety.safe_write(
                bridge,
                **prepared.safe_write_kwargs(tool="mixer_set_volume"),
            )
            if res.get("dry_run"):
                return wr.workflow_report(
                    workflow="mix_review_apply",
                    title="Apply Mix Review Adjustment",
                    mode="dry_run",
                    status="Dry-run only",
                    summary={"proposed_changes": 1, "applied_changes": 0},
                    proposed_changes=[proposal],
                    notes=["Dry-run mode is enabled; no FL Studio project state was changed."],
                    safety={"read_only": True, "requires_explicit_approval": True},
                )
            before, after = res.get("before") or {}, res.get("after") or {}
            applied = after.get("vol_db") is not None and abs(after["vol_db"] - target_db) <= 0.6
            return wr.workflow_report(
                workflow="mix_review_apply",
                title="Apply Mix Review Adjustment",
                mode="applied",
                status="Applied" if applied else "Applied with readback mismatch",
                summary={"proposed_changes": 0, "applied_changes": 1},
                applied_changes=[
                    wr.applied_change(
                        id=f"mix_trim_track_{track}",
                        title=f"Trim mixer track {track} to {target_db:.1f} dB",
                        tool="fl_apply_mix_adjustment",
                        before=before,
                        requested_change={"kind": kind, "track": track, "target_db": target_db},
                        after=after,
                        safety_class="write-safe-required",
                        risk_level="low",
                        change_id=res.get("change_id"),
                        rollback=res.get("rollback"),
                        readback_ok=applied,
                    )
                ],
                safety={
                    "read_only": False,
                    "requires_explicit_approval": False,
                    "approval_received": True,
                },
                notes=["Rollback with fl_rollback_last_change if the result is not intended."],
                ok=bool(applied),
            )
        except Exception as e:
            return wr.workflow_report(
                workflow="mix_review_apply",
                title="Apply Mix Review Adjustment",
                mode="error",
                status="Apply failed",
                summary={"applied_changes": 0},
                diagnostics=[
                    wr.diagnostic(
                        id="mix_apply_error",
                        severity="error",
                        message=f"{type(e).__name__}: {e}",
                        evidence={"kind": kind, "track": track, "target_db": target_db},
                    )
                ],
                ok=False,
            )

    @mcp.tool(annotations={"title": "Start full-song peak watch (Mix Review)", **_RO})
    def fl_mix_watch_start(
        interval_ms: Annotated[
            int, Field(ge=50, le=1000, description="Poll interval per round in ms (default 150).")
        ] = 150,
    ) -> dict:
        """Begin a peak-HOLD watch: continuously sample every mixer track's peak,
        keeping a RUNNING MAX per track, until fl_mix_watch_stop. Tell the user to
        PLAY the whole song (or at least the loudest section / the drop) while this
        runs -- then stop for full-song-accurate level diagnosis. Read-only.

        Safety: Read-Only.
        """
        try:
            bridge = get_bridge()
            tracks = fetch_all_pages(bridge, protocol.CMD_MIXER_LIST_TRACKS, "tracks").get(
                "tracks", []
            )
            indices = [t.get("i", t.get("index")) for t in tracks]
            r = md.get_watcher().start(bridge, indices, interval_ms=interval_ms)
            if not r.get("ok"):
                return {
                    "ok": False,
                    "error": r.get("error"),
                    "hint": "a watch is already running -- call fl_mix_watch_stop to finish it",
                }
            return {
                "ok": True,
                "watching_tracks": r["watching"],
                "interval_ms": r["interval_ms"],
                "message": "Watching peaks (running max). PLAY the full song / the drop, "
                "then call fl_mix_watch_stop for full-song diagnosis.",
            }
        except Exception as e:
            return {"ok": False, "error": f"{type(e).__name__}: {e}"}

    @mcp.tool(annotations={"title": "Peak watch status (Mix Review)", **_RO})
    def fl_mix_watch_status() -> dict:
        """Is a peak watch running, and for how long / how many polls so far?

        Safety: Read-Only.
        """
        return {"ok": True, **md.get_watcher().status()}

    @mcp.tool(annotations={"title": "Stop peak watch + review mix", **_RO})
    def fl_mix_watch_stop() -> dict:
        """Stop the peak watch and diagnose on the FULL-SONG running-max peaks
        captured across the whole watch (accurate clipping/headroom/imbalance vs
        the ~1.2s snapshot). Read-only -- proposes fixes, applies nothing.

        Safety: Read-Only.
        """
        try:
            peaks_lin, reads, elapsed = md.get_watcher().stop()
            if not peaks_lin or reads == 0 or max(peaks_lin.values(), default=0.0) <= 0.0:
                return wr.workflow_report(
                    workflow="mix_review",
                    title="Mix Review Watch",
                    mode="error",
                    status="No peaks captured",
                    summary={"reads": reads, "elapsed_s": round(elapsed, 1)},
                    diagnostics=[
                        wr.diagnostic(
                            id="no_watch_peaks",
                            severity="error",
                            message="No peaks captured. Was the song playing during the watch?",
                        )
                    ],
                    ok=False,
                )
            snap = md.gather_snapshot(get_bridge(), peaks_override=peaks_lin)
        except Exception as e:
            return wr.workflow_report(
                workflow="mix_review",
                title="Mix Review Watch",
                mode="error",
                status="Watch review failed",
                summary={"diagnostics": 0, "proposed_changes": 0},
                diagnostics=[
                    wr.diagnostic(
                        id="mix_watch_stop_error",
                        severity="error",
                        message=f"{type(e).__name__}: {e}",
                    )
                ],
                ok=False,
            )
        report = _result(snap, {"level": 2})
        report["title"] = "Mix Review Watch"
        report["metadata"].update(
            {
                "peak_source": "watch (full-song running max)",
                "watch": {"reads": reads, "elapsed_s": round(elapsed, 1)},
            }
        )
        report["notes"] = [
            "Levels are full-song maxima and are suitable for clipping/headroom review.",
            *report.get("notes", []),
        ]
        report["json_report"] = {
            key: value
            for key, value in report.items()
            if key not in {"json_report", "markdown_report"}
        }
        report["markdown_report"] = wr.render_markdown(report["json_report"])
        return report

    @mcp.tool(annotations={"title": "Review gain staging", **_RO})
    def fl_gain_stage() -> dict:
        """Propose per-track fader trims so each track's peak sits in a healthy
        band (~-12..-6 dBFS, aim -9) and the Master keeps -3..-6 dB headroom.
        READ-ONLY proposals -- apply approved ones via fl_apply_mix_adjustment (rollback).

        Uses FULL-SONG peaks from a recent watch (fl_mix_watch_start -> play ->
        fl_mix_watch_stop) when available; else a ~1.2s snapshot (prefer watch).
        FL's fader is POST-chain, so this sets a track's OUTPUT level, not a true
        pre-plugin input trim.

        Safety: Read-Only.
        """
        try:
            bridge = get_bridge()
            wmax = md.get_watcher().last_max()
            snap = md.gather_snapshot(bridge, peaks_override=wmax or None)
            if not (wmax or snap.get("levels_valid")):
                return wr.workflow_report(
                    workflow="gain_stage_review",
                    title="Gain Staging Review",
                    mode="diagnostic",
                    status="Needs level evidence",
                    summary={"diagnostics": 0, "proposed_changes": 0},
                    notes=[
                        "No level data. Press play or run watch mode, then call this tool again."
                    ],
                    safety={"read_only": True, "requires_explicit_approval": False},
                )
            plan = md.gain_stage_plan(snap)
        except Exception as e:
            return wr.workflow_report(
                workflow="gain_stage_review",
                title="Gain Staging Review",
                mode="error",
                status="Gain-stage review failed",
                summary={"diagnostics": 0, "proposed_changes": 0},
                diagnostics=[
                    wr.diagnostic(
                        id="gain_stage_error",
                        severity="error",
                        message=f"{type(e).__name__}: {e}",
                    )
                ],
                ok=False,
            )
        proposals = [
            _proposal_from_plan(p, index=index, source="gain_stage")
            for index, p in enumerate(plan["plans"], start=1)
        ]
        used_rule_ids = sorted(
            {rule_id for proposal in proposals for rule_id in (proposal.get("kb_rule_ids") or [])}
        )
        return wr.workflow_report(
            workflow="gain_stage_review",
            title="Gain Staging Review",
            mode="proposal",
            status="Gain-stage plan generated",
            summary={"target_db": plan["target_db"], "band": plan["band"]},
            proposed_changes=proposals,
            notes=[
                *plan["notes"],
                "Apply approved trims one at a time. "
                "Skip alternative Master trim if source trims were applied.",
            ],
            kb_policy_refs=kb_policy.rule_refs(used_rule_ids),
            metadata={
                "peak_source": "watch (full-song)"
                if wmax
                else snap.get("peak_window", {}).get("source"),
            },
            safety={"read_only": True, "requires_explicit_approval": bool(proposals)},
        )

    @mcp.tool(annotations={"title": "Reference match (level/balance)", **_RO})
    def fl_reference_match(
        reference_audio_path: Annotated[
            str, Field(description="Path to a reference WAV/MP3 to compare against.")
        ],
    ) -> dict:
        """Compare your mix's LEVEL + rough tonal BALANCE to a reference track.
        READ-ONLY. Analyzes the reference FILE (overall level + low/mid/high
        spectral-band shares) and your mix (Master peak for level + a ROUGH
        name-based band estimate). HONEST: a level/balance compare, NOT a spectral
        match -- FL doesn't expose its output audio, so the your-mix balance is
        estimated from track names + peaks. Suggests adjustments; applies nothing.

        Safety: Read-Only.
        """
        import os

        if not os.path.isfile(reference_audio_path):
            return {"ok": False, "error": f"file not found: {reference_audio_path}"}
        try:
            from .audio import analyze_bands

            ref = analyze_bands(reference_audio_path)
            wmax = md.get_watcher().last_max()
            snap = md.gather_snapshot(get_bridge(), peaks_override=wmax or None)
        except Exception as e:
            return {"ok": False, "error": f"{type(e).__name__}: {e}"}
        if not (wmax or snap.get("levels_valid")):
            return {
                "ok": True,
                "needs_levels": True,
                "reference": ref,
                "guidance": "Reference analyzed, but no mix level data -- press PLAY or run "
                "watch mode (fl_mix_watch_start -> play -> stop), then call again.",
            }
        bal = md.mix_band_balance(snap)
        master = next((t for t in snap["tracks"] if t.get("index") == 0), None)
        mix_peak = master.get("peak_db") if master else None
        level_delta = (
            round(mix_peak - ref["peak_db"], 1)
            if (mix_peak is not None and ref.get("peak_db") is not None)
            else None
        )
        band_cmp = {}
        for b in ("low", "mid", "high"):
            r = ref.get("bands_pct", {}).get(b, 0.0)
            m = bal["bands_pct"][b]
            band_cmp[b] = {
                "reference_pct": r,
                "your_mix_pct": m,
                "delta_pct": round(m - r, 1),
                "rough_db": round(10 * math.log10((m or 0.01) / (r or 0.01)), 1),
            }
        return {
            "ok": True,
            "reference": ref,
            "your_mix_balance": bal,
            "your_mix_peak_db": mix_peak,
            "peak_source": "watch (full-song)"
            if wmax
            else snap.get("peak_window", {}).get("source"),
            "level_delta_db": level_delta,
            "band_comparison": band_cmp,
            "honest": "Level + ROUGH name-based balance only. Your-mix balance is estimated from "
            "track names + peaks, NOT FL's output spectrum. Reference bands are real "
            "(file analysis). +level_delta = your mix hotter; +band delta_pct = your "
            "mix has more energy in that band than the reference.",
            "kb_policy_refs": kb_policy.rule_refs(
                ["master_peak_boundary", "mix_doctor_existing_plugin_only"]
            ),
            "guidance": (
                "Nudge via fl_apply_eq_intent (balance) / fl_apply_mix_adjustment (level): e.g. "
                "positive low delta -> high-pass/trim lows; negative high delta -> add_air."
            ),
        }

"""Read-only Runtime workflows for v3 product and audio-evidence slices."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .. import protocol
from ..analysis.audio_features import FeatureExtractor
from ..analysis.schema import (
    AnalysisReport,
    Coverage,
    EntityRef,
    Finding,
    Freshness,
    Prerequisite,
)
from ..analysis.scoring import confidence_from_coverage, risk_from_severities
from ..music import preset_library
from .audio_worker import sha256_file
from .core import RuntimeCore

_STATIC_TTL_SECONDS = 120
_SHORT_AUDIO_LIMIT_SECONDS = 180.0


def run_product_workflow(
    runtime: RuntimeCore,
    workflow_id: str,
    *,
    bridge: Any | None,
    inputs: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Run one v3 read-only product workflow and store its canonical report."""
    payload = dict(inputs or {})
    runners = {
        "preflight": _run_preflight,
        "jam_2_project": _run_jam_to_project,
        "sidechain_routing_check": _run_sidechain_check,
        "plugin_assistant": _run_plugin_assistant,
        "preset_assistant": _run_preset_assistant,
        "audio_evidence": _run_audio_evidence,
    }
    runner = runners.get(workflow_id)
    if runner is None:
        raise ValueError(f"product workflow execution is not available for {workflow_id!r}")
    report = runner(runtime, bridge=bridge, inputs=payload)
    return runtime.add_report(report).to_dict()


def _run_preflight(
    runtime: RuntimeCore,
    *,
    bridge: Any | None,
    inputs: dict[str, Any],
) -> AnalysisReport:
    del inputs
    snapshot = _require_snapshot(runtime, bridge)
    findings: list[Finding] = []
    proposals: list[dict[str, Any]] = []
    unrouted = [
        row
        for row in snapshot.channels
        if not isinstance(row.get("target_mixer_track"), int)
        or row.get("target_mixer_track") == 0
    ]
    if unrouted:
        entities = tuple(
            EntityRef(
                "channel",
                f"channel:{_row_index(row)}",
                str(row.get("name") or f"Channel {_row_index(row)}"),
            )
            for row in unrouted[:12]
        )
        findings.append(
            _finding(
                "preflight.unrouted_channels",
                "Channels routed only to Master need review",
                "medium",
                evidence={"count": len(unrouted)},
                entities=entities,
                confidence=90,
            )
        )
        first = _row_index(unrouted[0])
        proposals.append(
            {
                "id": "preflight.route_one_channel",
                "title": f"Route channel {first} to a free mixer track",
                "tool": "fl_apply_project_cleanup_step",
                "observed_state": {"channel": first, "target_mixer_track": 0},
                "proposed_state": {
                    "routing": [{"channel": first, "mode": "free"}],
                    "approved": True,
                },
                "safety_class": "write-safe-required",
                "risk_level": "low",
                "requires_explicit_approval": True,
                "readback_expectation": "Read back the channel mixer target.",
                "rollback_expectation": "Restore the previous mixer target from the changelog.",
                "status": "proposed",
            }
        )

    loud_clips = [
        row
        for row in snapshot.channels
        if str((row.get("type") or {}).get("label") or "").lower() == "audioclip"
        and _as_float(row.get("vol_norm", row.get("vol"))) > 0.8
    ]
    if loud_clips:
        findings.append(
            _finding(
                "preflight.loud_audio_clips",
                "High Audio Clip channel levels need review",
                "low",
                evidence={"count": len(loud_clips), "threshold_normalized": 0.8},
                confidence=85,
            )
        )

    missing = list(snapshot.coverage.missing)
    missing.append("live_meter_window")
    risk = risk_from_severities(tuple(row.severity for row in findings))
    return _static_report(
        runtime,
        snapshot,
        workflow="preflight",
        title="Preflight",
        findings=findings,
        coverage=Coverage(
            required=snapshot.coverage.required + 1,
            available=snapshot.coverage.available,
            missing=tuple(dict.fromkeys(missing)),
        ),
        risk_score=risk,
        confidence_score=confidence_from_coverage(
            required=snapshot.coverage.required + 1,
            available=snapshot.coverage.available,
            evidence_mode="static_snapshot",
        ),
        limitations=(
            "No current Master peak evidence is available from this static preflight.",
            "Stretch mode, Normalize, render, save, export, and mastering remain manual.",
        ),
        manual_checks=(
            {
                "id": "preflight.capture_loud_section",
                "title": "Capture the loudest section in Mix Review watch mode.",
                "reason": "Static project metadata cannot prove output headroom or clipping.",
            },
            {
                "id": "preflight.manual_export_checks",
                "title": "Check Stretch mode, Normalize, render settings, and mastering manually.",
                "reason": "These actions are API-limited or excluded from automation.",
            },
        ),
        next_actions=(
            {
                "type": "run_workflow",
                "workflow": "mix_review",
                "label": "Capture loud-section level evidence",
            },
        ),
        proposed_changes=tuple(proposals),
        metadata={"ready": not any(row.severity in {"high", "medium"} for row in findings)},
    )


def _run_jam_to_project(
    runtime: RuntimeCore,
    *,
    bridge: Any | None,
    inputs: dict[str, Any],
) -> AnalysisReport:
    del inputs
    snapshot = _require_snapshot(runtime, bridge)
    findings: list[Finding] = []
    proposals: list[dict[str, Any]] = []

    default_patterns = [
        row
        for row in snapshot.patterns
        if _is_default_name(row, "Pattern", "pattern")
    ]
    default_playlist = [
        row
        for row in snapshot.playlist_tracks
        if _is_default_name(row, "Track", "index")
    ]
    if default_patterns:
        findings.append(
            _finding(
                "jam_2_project.default_patterns",
                "Pattern names do not describe the jam structure",
                "low",
                evidence={"count": len(default_patterns)},
                entities=tuple(
                    EntityRef(
                        "pattern",
                        f"pattern:{_row_index(row)}",
                        str(row.get("name") or ""),
                    )
                    for row in default_patterns[:12]
                ),
                confidence=95,
            )
        )
        for row in default_patterns[:8]:
            index = _row_index(row)
            proposals.append(
                {
                    "id": f"jam.rename_pattern_{index}",
                    "title": f"Rename pattern {index} after its musical role is confirmed",
                    "tool": "fl_pattern",
                    "observed_state": {"index": index, "name": row.get("name")},
                    "proposed_state": {
                        "action": "rename",
                        "params": {"index": index, "name": "<confirmed role>"},
                    },
                    "safety_class": "write-safe-required",
                    "risk_level": "low",
                    "requires_explicit_approval": True,
                    "readback_expectation": "Read back the pattern name.",
                    "rollback_expectation": "Restore the prior pattern name.",
                    "status": "proposed",
                }
            )
    if default_playlist:
        findings.append(
            _finding(
                "jam_2_project.default_playlist_tracks",
                "Playlist track names do not expose section ownership",
                "low",
                evidence={"count": len(default_playlist)},
                confidence=95,
            )
        )

    return _static_report(
        runtime,
        snapshot,
        workflow="jam_2_project",
        title="Structure Jammed Project",
        findings=findings,
        risk_score=risk_from_severities(tuple(row.severity for row in findings)),
        confidence_score=80,
        assumptions=(
            "Names are treated as labels, not proof of musical role or arrangement intent.",
        ),
        limitations=(
            "The workflow does not move Playlist clips, create an arrangement, "
            "delete content, or make taste decisions.",
            "Placeholder names require the producer to confirm the intended role "
            "before any rename.",
        ),
        manual_checks=(
            {
                "id": "jam.confirm_sections",
                "title": "Confirm section boundaries and musical roles in the Playlist.",
                "reason": (
                    "The FL API does not provide safe Playlist clip editing "
                    "for this workflow."
                ),
            },
        ),
        next_actions=(
            {
                "type": "manual_check",
                "label": "Confirm pattern and Playlist roles",
            },
            {
                "type": "run_workflow",
                "workflow": "project_organizer",
                "label": "Review safe naming and routing proposals",
            },
        ),
        proposed_changes=tuple(proposals),
        metadata={
            "parent_workflow": "project_organizer",
            "mode": "planning_and_proposals_only",
        },
    )


def _run_sidechain_check(
    runtime: RuntimeCore,
    *,
    bridge: Any | None,
    inputs: dict[str, Any],
) -> AnalysisReport:
    del inputs
    snapshot = _require_snapshot(runtime, bridge)
    routes: list[tuple[int, int]] = []
    findings: list[Finding] = []
    for row in snapshot.routing:
        source = _row_index(row)
        for route in row.get("routes_to") or ():
            if not isinstance(route, dict):
                continue
            destination = _as_int(route.get("dst"))
            level = _as_float_or_none(route.get("level"))
            if destination is not None and level == 0.0:
                routes.append((source, destination))

    if routes:
        findings.append(
            _finding(
                "sidechain_routing_check.sidechain_routes",
                "Sidechain-only mixer routes are present",
                "info",
                evidence={
                    "routes": [
                        {"source": source, "destination": destination}
                        for source, destination in routes[:24]
                    ]
                },
                entities=tuple(
                    EntityRef("mixer_track", f"mixer:{source}")
                    for source, _destination in routes[:12]
                ),
                confidence=95,
            )
        )
    else:
        findings.append(
            _finding(
                "sidechain_routing_check.no_route_evidence",
                "No sidechain-only mixer route was detected",
                "info",
                evidence={"routing_rows": len(snapshot.routing)},
                confidence=75,
            )
        )

    return _static_report(
        runtime,
        snapshot,
        workflow="sidechain_routing_check",
        title="Sidechain Routing Check",
        findings=findings,
        risk_score=0,
        confidence_score=85 if routes else 70,
        assumptions=(
            "A route level of 0.0 is treated as sidechain-only routing evidence.",
            "Routing presence does not prove that a receiving plugin uses the sidechain input.",
        ),
        limitations=(
            "Plugin detector assignment and plugin-specific sidechain parameters are not inferred.",
            "Plugin loading and unknown parameter writes remain manual.",
        ),
        manual_checks=(
            {
                "id": "sidechain.verify_receiver",
                "title": "Verify the receiving plugin input and detector source.",
                "reason": "Routing metadata cannot prove plugin-internal sidechain configuration.",
            },
        ),
        next_actions=(
            {
                "type": "manual_check",
                "label": "Verify the receiving plugin sidechain input",
            },
        ),
        metadata={"sidechain_routes": len(routes), "routing_facts": routes},
    )


def _run_plugin_assistant(
    runtime: RuntimeCore,
    *,
    bridge: Any | None,
    inputs: dict[str, Any],
) -> AnalysisReport:
    track = inputs.get("track")
    if track is None:
        return _manual_target_report(
            runtime,
            workflow="plugin_assistant",
            title="Plugin Assistant",
            missing="mixer_track_target",
            manual_title="Choose one mixer track to inspect.",
            limitation=(
                "The assistant does not scan every mixer track automatically "
                "and cannot load plugins."
            ),
        )
    if not isinstance(track, int) or isinstance(track, bool) or track < 0:
        raise ValueError("plugin_assistant track must be a non-negative integer")
    if bridge is None:
        raise ValueError("plugin_assistant requires an FL Studio bridge")
    result = bridge.call(protocol.CMD_PLUGIN_LIST, {"track": track}) or {}
    slots = [dict(row) for row in result.get("slots") or () if isinstance(row, dict)]
    findings = [
        _finding(
            f"plugin_assistant.track_{track}",
            f"{len(slots)} loaded plugin slot(s) found on mixer track {track}",
            "info",
            evidence={"track": track, "slots": slots},
            entities=(EntityRef("mixer_track", f"mixer:{track}"),),
            confidence=95,
        )
    ]
    now = _now()
    return AnalysisReport(
        workflow="plugin_assistant",
        title="Plugin Assistant",
        analysis_mode="static_snapshot",
        evidence_mode="loaded_plugin_inventory",
        created_at=now.isoformat(),
        freshness=_freshness(now, ()),
        coverage=Coverage(required=1, available=1),
        prerequisites=(Prerequisite("mixer_track_target", "ok"),),
        risk_score=0,
        health_score=100,
        confidence_score=95,
        findings=tuple(findings),
        limitations=(
            "Only already-loaded plugins are inspected.",
            "Parameter changes require a known live parameter and an existing rollback-safe tool.",
            "Plugin loading and insertion remain manual.",
        ),
        next_actions=(
            {
                "type": "manual_check",
                "label": "Choose a loaded plugin and inspect its named parameters",
            },
        ),
        safety={"read_only": True, "project_changes": False},
        metadata={"track": track, "slots": slots},
    )


def _run_preset_assistant(
    runtime: RuntimeCore,
    *,
    bridge: Any | None,
    inputs: dict[str, Any],
) -> AnalysisReport:
    del bridge
    plugin = str(inputs.get("plugin") or "").strip() or None
    description = str(inputs.get("description") or "").strip()
    library = preset_library.list_presets(plugin_filter=plugin)
    names = [
        name
        for rows in (library.get("presets") or {}).values()
        for name in rows
    ]
    matches = (
        preset_library.score_presets(names, description)
        if names and description
        else names[:15]
    )
    available = bool(library.get("found"))
    now = _now()
    return AnalysisReport(
        workflow="preset_assistant",
        title="Preset Assistant",
        analysis_mode="static_snapshot",
        evidence_mode="local_preset_name_inventory",
        created_at=now.isoformat(),
        freshness=_freshness(now, ()),
        coverage=Coverage(
            required=1,
            available=1 if available else 0,
            missing=() if available else ("local_preset_library",),
        ),
        prerequisites=(
            Prerequisite("local_preset_library", "ok" if available else "unavailable"),
        ),
        risk_score=0,
        health_score=100 if available else 0,
        confidence_score=75 if available else 0,
        findings=(
            _finding(
                "preset_assistant.inventory",
                (
                    f"{len(names)} preset name(s) available for {plugin}"
                    if plugin
                    else f"{int(library.get('count') or 0)} preset name(s) indexed locally"
                ),
                "info",
                evidence={"plugin": plugin, "matches": matches[:15]},
                confidence=75,
            ),
        )
        if available
        else (),
        assumptions=(
            "Suggestions use preset names only and do not evaluate the sound.",
        ),
        limitations=(
            "Preset loading is manual because no verified rollback path exists.",
            "Name matches are suggestions, not audio evidence.",
        ),
        manual_checks=(
            {
                "id": "preset.load_manually",
                "title": "Load the selected preset in the plugin UI.",
                "reason": "Preset switching is not exposed as an MCP write.",
            },
        ),
        safety={"read_only": True, "project_changes": False},
        metadata={
            "plugin": plugin,
            "description": description or None,
            "matches": matches[:15],
            "library": library,
        },
    )


def _run_audio_evidence(
    runtime: RuntimeCore,
    *,
    bridge: Any | None,
    inputs: dict[str, Any],
) -> AnalysisReport:
    del runtime, bridge
    evidence_kind = str(inputs.get("evidence_kind") or "rendered_master")
    workflow_links = tuple(
        str(value)
        for value in inputs.get("workflow_links") or ()
        if str(value).strip()
    )
    return build_audio_evidence_report(
        str(inputs.get("path") or ""),
        evidence_kind=evidence_kind,
        workflow_links=workflow_links,
    )


def build_audio_evidence_report(
    path_value: str,
    *,
    evidence_kind: str = "rendered_master",
    workflow_links: tuple[str, ...] = (),
) -> AnalysisReport:
    """Build file-hash-scoped rendered-audio evidence without touching FL Studio."""
    path = Path(path_value).expanduser()
    if evidence_kind not in {"rendered_master", "stem", "candidate"}:
        raise ValueError("audio_evidence evidence_kind must be rendered_master, stem, or candidate")
    if not path.is_file():
        raise ValueError(f"audio evidence file not found: {path}")

    digest = sha256_file(path)
    features, unavailable_metrics = _analyze_audio_file(path)
    duration = _as_float(features.get("duration_sec"))
    if evidence_kind in {"stem", "candidate"} and duration > _SHORT_AUDIO_LIMIT_SECONDS:
        raise ValueError(
            f"{evidence_kind} evidence must be {_SHORT_AUDIO_LIMIT_SECONDS:.0f} seconds or shorter"
        )
    now = _now()
    observation_id = f"audio:{digest}"
    confidence = 95 if evidence_kind == "rendered_master" else 90
    return AnalysisReport(
        workflow="audio_evidence",
        title="Audio Evidence",
        analysis_mode="rendered_audio",
        evidence_mode=evidence_kind,
        created_at=now.isoformat(),
        project_fingerprint=f"file:{digest}",
        snapshot_id=f"file:{digest}",
        freshness=Freshness(
            status="fresh",
            created_at=now.isoformat(),
            invalidates_on=("file_hash_change",),
            source_observation_ids=(observation_id,),
            details="Valid while the source file hash is unchanged.",
        ),
        coverage=Coverage(required=1, available=1),
        prerequisites=(Prerequisite("rendered_audio_features", "ok"),),
        risk_score=0,
        health_score=100,
        confidence_score=confidence,
        findings=(
            _finding(
                f"audio_evidence.{evidence_kind}",
                "Rendered-audio features are available",
                "info",
                evidence={
                    "duration_sec": duration,
                    "rms_db": features.get("rms_db"),
                    "peak_db": features.get("peak_db"),
                    "bands_pct": features.get("bands_pct"),
                    "tempo_bpm": features.get("tempo_bpm"),
                    "key": features.get("key"),
                },
                confidence=confidence,
                evidence_mode="rendered_audio",
                source_observation_ids=(observation_id,),
            ),
        ),
        assumptions=(
            "Tempo and key are estimates and may be ambiguous.",
        ),
        limitations=(
            "No FL Studio render was triggered.",
            "True loudness, phase correlation, mono cancellation, and stem "
            "overlap are not claimed.",
            *(
                (f"Unavailable metrics: {', '.join(unavailable_metrics)}.",)
                if unavailable_metrics
                else ()
            ),
        ),
        source_observations=(observation_id,),
        next_actions=tuple(
            {
                "type": "evidence_upgrade",
                "workflow": workflow,
                "label": f"Use this file evidence in {workflow.replace('_', ' ')}",
            }
            for workflow in workflow_links
        ),
        safety={"read_only": True, "project_changes": False, "external_write": False},
        metadata={
            "file": {
                "path": str(path),
                "sha256": digest,
                "size_bytes": path.stat().st_size,
                "duration_sec": duration,
            },
            "features": features,
            "workflow_links": list(workflow_links),
            "level": "L2" if evidence_kind == "rendered_master" else "L3",
            "unavailable_metrics": unavailable_metrics,
        },
    )


def _require_snapshot(runtime: RuntimeCore, bridge: Any | None):
    if bridge is None:
        raise ValueError("workflow requires an FL Studio bridge")
    return runtime.get_static_project_snapshot(bridge)


def _static_report(
    runtime: RuntimeCore,
    snapshot,
    *,
    workflow: str,
    title: str,
    findings: list[Finding],
    risk_score: int,
    confidence_score: int,
    coverage: Coverage | None = None,
    assumptions: tuple[str, ...] = (),
    limitations: tuple[str, ...] = (),
    manual_checks: tuple[dict[str, Any], ...] = (),
    next_actions: tuple[dict[str, Any], ...] = (),
    proposed_changes: tuple[dict[str, Any], ...] = (),
    metadata: dict[str, Any] | None = None,
) -> AnalysisReport:
    now = _now()
    source_ids = tuple(snapshot.source_observation_ids)
    effective_coverage = coverage or snapshot.coverage
    return AnalysisReport(
        workflow=workflow,
        title=title,
        analysis_mode="static_snapshot",
        evidence_mode="static_snapshot_only",
        created_at=now.isoformat(),
        project_fingerprint=snapshot.project_fingerprint,
        freshness=Freshness(
            status=effective_coverage.status,
            created_at=now.isoformat(),
            valid_until=(now + timedelta(seconds=_STATIC_TTL_SECONDS)).isoformat(),
            invalidates_on=(
                "fl_disconnect",
                "project_structure_change",
                "mixer_structure_change",
                "routing_change",
            ),
            source_observation_ids=source_ids,
        ),
        coverage=effective_coverage,
        prerequisites=(
            Prerequisite(
                "fl_session_alive",
                "ok" if effective_coverage.available else "unavailable",
            ),
            Prerequisite(
                "static_project_snapshot",
                "ok" if effective_coverage.available else "unavailable",
            ),
        ),
        risk_score=risk_score,
        confidence_score=confidence_score,
        findings=tuple(findings),
        assumptions=assumptions,
        limitations=limitations,
        manual_checks=manual_checks,
        source_observations=source_ids,
        next_actions=next_actions,
        proposed_changes=proposed_changes,
        safety={
            "read_only": True,
            "project_changes": False,
            "requires_explicit_approval": bool(proposed_changes),
        },
        metadata=dict(metadata or {}),
    )


def _manual_target_report(
    runtime: RuntimeCore,
    *,
    workflow: str,
    title: str,
    missing: str,
    manual_title: str,
    limitation: str,
) -> AnalysisReport:
    now = _now()
    return AnalysisReport(
        workflow=workflow,
        title=title,
        analysis_mode="manual_check",
        evidence_mode="manual_check",
        created_at=now.isoformat(),
        runtime_session_id=runtime.session.id,
        freshness=Freshness(status="partial", created_at=now.isoformat()),
        coverage=Coverage(required=1, available=0, missing=(missing,)),
        prerequisites=(Prerequisite(missing, "missing"),),
        risk_score=0,
        health_score=0,
        confidence_score=0,
        limitations=(limitation,),
        manual_checks=(
            {"id": f"{workflow}.{missing}", "title": manual_title, "reason": limitation},
        ),
        next_actions=({"type": "provide_input", "field": missing, "label": manual_title},),
        safety={"read_only": True, "project_changes": False},
    )


def _finding(
    finding_id: str,
    title: str,
    severity: str,
    *,
    evidence: dict[str, Any],
    confidence: int,
    entities: tuple[EntityRef, ...] = (),
    evidence_mode: str = "static_snapshot",
    source_observation_ids: tuple[str, ...] = (),
) -> Finding:
    return Finding(
        id=finding_id,
        rule_id=finding_id,
        title=title,
        severity=severity,
        risk_score=risk_from_severities((severity,)),
        confidence_score=confidence,
        evidence_mode=evidence_mode,
        entities=entities,
        evidence=(evidence,),
        source_observation_ids=source_observation_ids,
    )


def _freshness(now: datetime, source_ids: tuple[str, ...]) -> Freshness:
    return Freshness(
        status="fresh",
        created_at=now.isoformat(),
        valid_until=(now + timedelta(seconds=_STATIC_TTL_SECONDS)).isoformat(),
        source_observation_ids=source_ids,
    )


def _analyze_audio_file(path: Path) -> tuple[dict[str, Any], list[str]]:
    extracted = FeatureExtractor().extract(path)
    summary = extracted["summary"]
    bands = summary["band_energy"]
    features = {
        "path": str(path),
        "duration_sec": summary["duration_seconds"],
        "rms_db": summary["rms_dbfs"],
        "peak_db": summary["peak_dbfs"],
        "tempo_bpm": None,
        "key": None,
        "bands_pct": {
            "low": round(100 * (bands["sub"] + bands["low"]), 1),
            "mid": round(100 * bands["mid"], 1),
            "high": round(100 * bands["high"], 1),
        },
        "note": "Tempo and key are separate optional MIR features.",
    }
    return features, ["tempo", "key"]


def _is_default_name(row: dict[str, Any], prefix: str, index_key: str) -> bool:
    index = _as_int(row.get(index_key, row.get("index", row.get("i"))))
    name = str(row.get("name") or "").strip()
    return not name or (index is not None and name in {f"{prefix} {index}", prefix})


def _row_index(row: dict[str, Any]) -> int:
    return int(row.get("channel", row.get("index", row.get("i", row.get("pattern", 0)))))


def _as_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _as_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _as_float_or_none(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _now() -> datetime:
    return datetime.now(timezone.utc)

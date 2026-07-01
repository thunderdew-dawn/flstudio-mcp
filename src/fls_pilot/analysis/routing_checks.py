"""Pure routing audit checks shared by MCP and Control Center surfaces."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .. import project_templates as templates
from .. import protocol

ROUTING_MODE_LEVEL_1 = "level_1_static"
ROUTING_MODE_LEVEL_2 = "level_2_signal_flow"
TEMPLATE_COMPLIANCE_AUTO = "auto_detect"
TEMPLATE_COMPLIANCE_MANUAL = "manual_select"
TEMPLATE_COMPLIANCE_OFF = "off"

ROUTING_LEVEL_LABELS = {
    ROUTING_MODE_LEVEL_1: "Static Routing & Settings Audit (Lvl 1)",
    ROUTING_MODE_LEVEL_2: "Signal Flow Assisted Routing Audit (Lvl 2)",
}
TEMPLATE_COMPLIANCE_LABELS = {
    TEMPLATE_COMPLIANCE_AUTO: "Auto-detect Template Compliance",
    TEMPLATE_COMPLIANCE_MANUAL: "Select Template Profile",
    TEMPLATE_COMPLIANCE_OFF: "Template Compliance Off",
}

LEVEL_2_MARKER_NAMES = (
    "loudest",
    "loudest section",
    "drop",
    "main drop",
    "chorus",
    "full mix",
    "test loop",
    "routing test",
    "analysis loop",
)

_DEFAULT_ROLE_ALIASES = {
    "master": ("master",),
    "premaster": (
        "premaster",
        "pre master",
        "pre-master",
        "mix bus",
        "mixbus",
        "final bus",
    ),
    "drum_bus": ("drum bus", "drums", "bus drums", "perc bus", "percussion bus"),
    "kick_bus": ("kick bus", "bus kick", "kick mix"),
    "bass_bus": ("bass bus", "lowend bus", "low-end bus", "sub bus", "bass mix"),
    "lowend_bus": ("lowend", "low-end", "sub mix", "kick bass", "kick+bass"),
    "synth_bus": (
        "synth bus",
        "lead bus",
        "music bus",
        "instrument bus",
        "instruments",
    ),
    "fx_bus": ("fx bus", "send bus", "return bus", "reverb bus", "delay bus"),
    "vocal_bus": ("vocal bus", "vox bus", "vocals"),
    "reference": ("reference", "ref", "ref track", "reference track"),
    "sidechain_control": ("sidechain", "sc", "ghost kick", "trigger"),
    "print_or_render": ("print", "render", "record", "resample"),
    "template_reserved_placeholder": ("reserved", "placeholder", "empty template"),
}

_SOURCE_ROLE_ALIASES = {
    "kick": ("kick",),
    "bass": ("bass", "sub", "808", "lowend", "low-end"),
    "drums_or_percussion": (
        "drum",
        "perc",
        "percussion",
        "hat",
        "hihat",
        "hi-hat",
        "snare",
        "clap",
        "cymbal",
    ),
    "synth_lead_arp_pad": (
        "synth",
        "lead",
        "arp",
        "acid",
        "pad",
        "pluck",
        "instrument",
        "music",
    ),
    "fx_return": ("fx", "reverb", "delay", "return", "riser", "impact", "sweep"),
    "vocal": ("vocal", "vox"),
    "reference": ("reference", "ref track", "ref"),
    "sidechain_control": ("sidechain", "ghost kick", "trigger", "sc"),
    "print_or_render": ("print", "render", "record", "resample"),
}

_DEFAULT_EXPECTED_PATHS = (
    {
        "source_role": "kick",
        "expected_path": ("kick_or_drum_bus", "premaster", "master"),
        "allowed_direct_roles": ("premaster",),
        "direct_to_master_allowed": False,
    },
    {
        "source_role": "bass",
        "expected_path": ("bass_or_lowend_bus", "premaster", "master"),
        "allowed_direct_roles": ("premaster",),
        "direct_to_master_allowed": False,
    },
    {
        "source_role": "drums_or_percussion",
        "expected_path": ("drum_or_perc_bus", "premaster", "master"),
        "allowed_direct_roles": ("premaster",),
        "direct_to_master_allowed": False,
    },
    {
        "source_role": "synth_lead_arp_pad",
        "expected_path": ("synth_or_music_bus", "premaster", "master"),
        "allowed_direct_roles": ("premaster",),
        "direct_to_master_allowed": False,
    },
    {
        "source_role": "fx_return",
        "expected_path": ("fx_bus_or_premaster", "master"),
        "direct_to_master_allowed": "profile_dependent",
    },
    {
        "source_role": "vocal",
        "expected_path": ("vocal_bus", "premaster", "master"),
        "allowed_direct_roles": ("premaster",),
        "direct_to_master_allowed": False,
    },
    {
        "source_role": "reference",
        "expected_path": ("reference_bus_or_monitor_only",),
        "must_not_feed_master_export": True,
    },
    {
        "source_role": "sidechain_control",
        "expected_path": ("sidechain_control_only",),
        "must_not_be_audible_on_master": True,
    },
    {
        "source_role": "print_or_render",
        "expected_path": ("print_or_render_bus",),
        "master_routing_allowed_only_when_auditioning": True,
    },
)

_EXPECTED_ROLE_GROUPS = {
    "kick_or_drum_bus": {"kick_bus", "drum_bus", "stem_bus"},
    "kick_bus_or_drum_bus": {"kick_bus", "drum_bus", "stem_bus"},
    "bass_or_lowend_bus": {"bass_bus", "lowend_bus", "stem_bus"},
    "bass_bus_or_lowend_bus": {"bass_bus", "lowend_bus", "stem_bus"},
    "lowend_bus": {"lowend_bus", "bass_bus", "stem_bus"},
    "drum_or_perc_bus": {"drum_bus", "stem_bus"},
    "synth_or_music_bus": {"synth_bus", "stem_bus"},
    "synth_or_lead_bus": {"synth_bus", "stem_bus"},
    "synth_or_atmos_bus": {"synth_bus", "stem_bus"},
    "fx_bus_or_premaster": {"fx_bus", "premaster"},
    "vocal_bus": {"vocal_bus", "stem_bus"},
    "premaster": {"premaster"},
    "master": {"master"},
    "reference_bus_or_monitor_only": {"reference"},
    "sidechain_control_only": {"sidechain_control"},
    "print_or_render_bus": {"print_or_render"},
}


@dataclass(frozen=True)
class RoutingAuditOptions:
    routing_check_mode: str = ROUTING_MODE_LEVEL_1
    template_compliance: str = TEMPLATE_COMPLIANCE_AUTO
    selected_template_profile: str | None = None
    playback_decision: str | None = None
    marker_name: str | None = None
    loop_duration_seconds: float | None = None

    @property
    def level(self) -> int:
        return 2 if self.routing_check_mode == ROUTING_MODE_LEVEL_2 else 1

    @property
    def display_name(self) -> str:
        return ROUTING_LEVEL_LABELS[self.routing_check_mode]

    @property
    def playback_required(self) -> bool:
        return self.level == 2

    @property
    def static_evidence_mode(self) -> str:
        return "static_snapshot_plus_meter_snapshot" if self.level == 2 else "static_snapshot_only"


def routing_audit_options_from_inputs(inputs: dict[str, Any] | None) -> RoutingAuditOptions:
    payload = dict(inputs or {})
    mode = str(payload.get("routing_check_mode") or payload.get("mode") or "").strip()
    if mode not in {ROUTING_MODE_LEVEL_1, ROUTING_MODE_LEVEL_2}:
        mode = ROUTING_MODE_LEVEL_1
    compliance = str(
        payload.get("template_compliance") or payload.get("template_compliance_mode") or ""
    ).strip()
    if compliance not in {
        TEMPLATE_COMPLIANCE_AUTO,
        TEMPLATE_COMPLIANCE_MANUAL,
        TEMPLATE_COMPLIANCE_OFF,
    }:
        compliance = TEMPLATE_COMPLIANCE_AUTO
    selected = (
        str(
            payload.get("selected_template_profile")
            or payload.get("template_profile_id")
            or payload.get("template_slug")
            or ""
        ).strip()
        or None
    )
    loop_duration = _as_float(payload.get("loop_duration_seconds"))
    return RoutingAuditOptions(
        routing_check_mode=mode,
        template_compliance=compliance,
        selected_template_profile=selected,
        playback_decision=str(payload.get("playback_decision") or "").strip() or None,
        marker_name=str(payload.get("marker_name") or "").strip() or None,
        loop_duration_seconds=loop_duration,
    )


def template_profile_catalog() -> list[dict[str, Any]]:
    rows = []
    for profile in templates.load_profiles():
        rows.append(
            {
                "profile_id": profile.get("template_slug"),
                "display_name": profile.get("template_name"),
                "genre_or_use_case": profile.get("genre_or_use_case"),
                "confidence": (profile.get("source") or {}).get("confidence"),
            }
        )
    return rows


def merge_channel_control_rows(
    routing_rows: list[dict[str, Any]],
    control_rows: list[dict[str, Any]] | tuple[dict[str, Any], ...] | None,
) -> list[dict[str, Any]]:
    by_index = {
        idx: dict(row) for row in control_rows or () if (idx := _channel_index(row)) is not None
    }
    merged = []
    for row in routing_rows:
        item = dict(row)
        idx = _channel_index(item)
        control = by_index.get(idx)
        if control:
            for key in ("pan", "mute", "solo", "vol_norm", "vol_db"):
                if key in control and item.get(key) is None:
                    item[key] = control.get(key)
        merged.append(item)
    return merged


def channel_mixer_discrepancy_findings(
    *,
    channels: list[dict[str, Any]],
    mixer_tracks: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    track_by_index = {idx: row for row in mixer_tracks if (idx := _track_index(row)) is not None}
    findings: list[dict[str, Any]] = []
    volume_divergence = []
    volume_conflict = []
    pan_divergence = []
    pan_conflict = []
    mute_divergence = []
    mute_conflict = []
    solo_divergence = []
    solo_conflict = []

    for channel in channels:
        target = _as_int(channel.get("target_mixer_track"))
        if target in (None, 0):
            continue
        track = track_by_index.get(target)
        if not track:
            continue
        item = _comparison_item(channel, track, target)

        channel_vol = _as_float(channel.get("vol_norm"))
        mixer_vol = _as_float(track.get("vol_norm"))
        if channel_vol is not None and mixer_vol is not None:
            diff = abs(channel_vol - mixer_vol)
            row = {**item, "channel_volume": channel_vol, "mixer_volume": mixer_vol}
            if (
                _near_silent(channel_vol) != _near_silent(mixer_vol)
                and max(channel_vol, mixer_vol) >= 0.65
            ):
                volume_conflict.append(row)
            elif diff >= 0.25:
                volume_divergence.append(row)

        channel_pan = _as_float(channel.get("pan"))
        mixer_pan = _as_float(track.get("pan"))
        if channel_pan is not None and mixer_pan is not None:
            diff = abs(channel_pan - mixer_pan)
            row = {**item, "channel_pan": channel_pan, "mixer_pan": mixer_pan}
            if channel_pan * mixer_pan < 0 and diff >= 1.4:
                pan_conflict.append(row)
            elif diff >= 0.55:
                pan_divergence.append(row)

        channel_mute = _as_bool(channel.get("mute"))
        mixer_mute = _as_bool(track.get("mute"))
        if channel_mute is not None and mixer_mute is not None and channel_mute != mixer_mute:
            row = {**item, "channel_mute": channel_mute, "mixer_mute": mixer_mute}
            mute_divergence.append(row)
            mute_conflict.append(row)

        channel_solo = _as_bool(channel.get("solo"))
        mixer_solo = _as_bool(track.get("solo"))
        if channel_solo is not None and mixer_solo is not None and channel_solo != mixer_solo:
            row = {**item, "channel_solo": channel_solo, "mixer_solo": mixer_solo}
            solo_divergence.append(row)
            solo_conflict.append(row)

    if volume_divergence:
        findings.append(
            _finding(
                "channel_mixer_volume_divergence",
                "low",
                "Channel and Mixer Volume Diverge",
                "Channel Rack volume and assigned Mixer Track volume differ. "
                "This may be intentional gain staging, but should be reviewed.",
                volume_divergence,
            )
        )
    if volume_conflict:
        findings.append(
            _finding(
                "channel_mixer_volume_conflict",
                "high",
                "Channel and Mixer Volume Conflict",
                "One side is near silent while the other is high. "
                "This is a strong gain-staging contradiction and should be reviewed.",
                volume_conflict,
            )
        )
    if pan_divergence:
        findings.append(
            _finding(
                "channel_mixer_pan_divergence",
                "low",
                "Channel and Mixer Pan Diverge",
                "Channel Rack panning and assigned Mixer Track panning differ. "
                "This may be intentional stereo placement, but should be reviewed.",
                pan_divergence,
            )
        )
    if pan_conflict:
        findings.append(
            _finding(
                "channel_mixer_pan_conflict",
                "critical",
                "Channel and Mixer Pan Conflict",
                "The Channel Rack and assigned Mixer Track use strongly conflicting pan "
                "settings. This may be intentional, but it is a strong contradiction "
                "and should be reviewed.",
                pan_conflict,
            )
        )
    if mute_divergence:
        findings.append(
            _finding(
                "channel_mixer_mute_state_divergence",
                "low",
                "Channel and Mixer Mute State Diverge",
                "Mute states differ between Channel Rack and Mixer Track. "
                "This can be intentional, but may explain missing or unexpected signal.",
                mute_divergence,
            )
        )
    if mute_conflict:
        findings.append(
            _finding(
                "channel_mixer_mute_conflict",
                "high",
                "Channel and Mixer Mute Conflict",
                "The Channel Rack and assigned Mixer Track have conflicting mute states. "
                "This should be reviewed before interpreting routing or signal-flow results.",
                mute_conflict,
            )
        )
    if solo_divergence:
        findings.append(
            _finding(
                "channel_mixer_solo_state_divergence",
                "low",
                "Channel and Mixer Solo State Diverge",
                "Solo states differ between Channel Rack and Mixer Track. "
                "Solo can be temporary, but it may cause misleading routing-check results.",
                solo_divergence,
            )
        )
    if solo_conflict:
        findings.append(
            _finding(
                "channel_mixer_solo_conflict",
                "high",
                "Channel and Mixer Solo Conflict",
                "The Channel Rack and assigned Mixer Track have conflicting solo states. "
                "This can cause misleading monitoring or routing-check behavior.",
                solo_conflict,
            )
        )
    return findings


def capture_signal_flow_evidence(
    bridge: Any,
    *,
    tracks: list[int],
    playback_used: bool,
    marker_name: str | None = None,
    loop_duration_seconds: float | None = None,
) -> dict[str, Any]:
    unique_tracks = sorted({int(track) for track in tracks if isinstance(track, int)})
    if not unique_tracks:
        return {
            "available": False,
            "playback_used": playback_used,
            "track_peaks": {},
            "limitations": ["No mixer tracks were available for meter capture."],
        }
    try:
        payload = bridge.call(protocol.CMD_MIXER_GET_ALL_PEAKS, {"tracks": unique_tracks[:32]})
    except Exception as exc:
        return {
            "available": False,
            "playback_used": playback_used,
            "track_peaks": {},
            "errors": [f"mixer_get_all_peaks -> {type(exc).__name__}: {exc}"],
            "limitations": [
                "Signal-flow meter snapshot could not be collected; "
                "Level 2 confirmation is unavailable."
            ],
        }
    scale = _as_float(payload.get("scale")) or 1000000.0
    returned_tracks = payload.get("tracks") or unique_tracks[:32]
    returned_peaks = payload.get("peaks") or []
    peaks: dict[int, float] = {}
    if len(returned_tracks) == len(returned_peaks):
        for track, raw_peak in zip(returned_tracks, returned_peaks, strict=False):
            idx = _as_int(track)
            value = _as_float(raw_peak)
            if idx is not None and value is not None:
                peaks[idx] = max(0.0, value / scale)
    available = bool(peaks)
    return {
        "available": available,
        "playback_used": playback_used,
        "marker_name": marker_name,
        "loop_duration_seconds": loop_duration_seconds,
        "active_threshold": 0.00001,
        "track_peaks": {str(track): peak for track, peak in peaks.items()},
        "limitations": [] if available else ["Signal-flow meter snapshot returned no peaks."],
    }


def template_compliance_result(
    *,
    channels: list[dict[str, Any]],
    routing: list[dict[str, Any]],
    mixer_tracks: list[dict[str, Any]],
    template_context: dict[str, Any],
    options: RoutingAuditOptions,
    signal_flow: dict[str, Any] | None = None,
) -> dict[str, Any]:
    compact = templates.compact_context(template_context) or {}
    selected_profile = _selected_profile(compact, options)
    profile_source = _profile_source(compact, options, selected_profile)
    confidence = _template_confidence(compact, options, selected_profile)
    enabled = options.template_compliance != TEMPLATE_COMPLIANCE_OFF
    summary = {
        "profile_id": selected_profile.get("template_slug") if selected_profile else None,
        "display_name": selected_profile.get("template_name") if selected_profile else None,
        "confidence": confidence,
        "profile_source": profile_source,
        "matched_roles_count": 0,
        "missing_expected_roles": [],
        "source_paths_checked": 0,
        "bypasses_detected": 0,
        "reference_or_sidechain_risks": 0,
        "compliance_status": "off" if not enabled else "unavailable",
    }
    if not enabled:
        return {"enabled": False, "findings": [], "summary": summary, "profile": None}

    findings: list[dict[str, Any]] = []
    if selected_profile:
        findings.append(
            _finding(
                "template.profile_detected",
                "info",
                "Template Profile Selected",
                f"{selected_profile.get('template_name')} template compliance is active "
                f"({profile_source}, confidence: {confidence}).",
                [{"template_profile_id": selected_profile.get("template_slug")}],
            )
        )
    else:
        findings.append(
            _finding(
                "template.low_confidence",
                "low",
                "Template Compliance Not Applied",
                "Template profile detection is unavailable or too weak. "
                "General routing checks still ran.",
                [],
            )
        )
        return {"enabled": True, "findings": findings, "summary": summary, "profile": None}

    if confidence == "low" and options.template_compliance == TEMPLATE_COMPLIANCE_AUTO:
        findings.append(
            _finding(
                "template.low_confidence",
                "low",
                "Template Detection Confidence Is Low",
                "Template profile detection confidence is low; high-severity template "
                "findings are suppressed unless a profile is manually selected.",
                [],
            )
        )

    track_by_index, routes_by_src, incoming_by_dst = _routing_maps(routing, mixer_tracks)
    role_by_track = _role_map(
        selected_profile,
        template_context,
        {idx: row.get("name") for idx, row in track_by_index.items()},
    )
    summary["matched_roles_count"] = sum(1 for roles in role_by_track.values() if roles)
    expected_by_source = _expected_paths_by_source(selected_profile)
    source_roles_present: set[str] = set()
    missing_roles: set[str] = set()
    bypasses = 0
    reference_risks = 0
    signal_findings: list[dict[str, Any]] = []
    reported_expected_bus_silent: set[tuple[int, int]] = set()
    reported_master_path_missing: set[int] = set()

    for channel in channels:
        source_role = _source_role(channel)
        if source_role is None:
            continue
        source_roles_present.add(source_role)
        target = _as_int(channel.get("target_mixer_track"))
        if target is None:
            continue
        expected = expected_by_source.get(source_role)
        target_path = _reachable_tracks(target, routes_by_src)
        path_roles = _path_roles(target_path, role_by_track)
        summary["source_paths_checked"] += 1
        direct_to_master = target == 0 or any(
            _as_int(route.get("dst")) == 0 for route in routes_by_src.get(target, ())
        )
        reaches_master = 0 in target_path or direct_to_master

        if source_role in {"reference", "sidechain_control"} and reaches_master:
            rule = (
                "template.reference_routed_to_master"
                if source_role == "reference"
                else "template.sidechain_control_routed_to_master"
            )
            title = (
                "Reference Track Routes To Master"
                if source_role == "reference"
                else "Sidechain Control Routes To Master"
            )
            findings.append(
                _finding(
                    rule,
                    _template_severity("critical", confidence, options),
                    title,
                    (
                        "A reference track appears to feed the master path and should be reviewed."
                        if source_role == "reference"
                        else (
                            "A sidechain trigger or ghost kick appears to feed the audible "
                            "master path and should be reviewed."
                        )
                    ),
                    [_template_channel_item(channel, target, track_by_index, source_role)],
                )
            )
            reference_risks += 1
            if _signal_active(signal_flow, target) and _signal_active(signal_flow, 0):
                signal_findings.append(
                    _finding(
                        (
                            "template.reference_active_to_master_signal_confirmed"
                            if source_role == "reference"
                            else "template.sidechain_trigger_audible_signal_confirmed"
                        ),
                        "critical",
                        title + " With Signal",
                        "Playback evidence confirms activity on the source and master path.",
                        [_template_channel_item(channel, target, track_by_index, source_role)],
                        signal_flow=signal_flow,
                    )
                )
            continue

        if not expected:
            continue
        expected_roles = _expected_bus_role_candidates(expected)
        if expected_roles and not _roles_available(expected_roles, role_by_track):
            missing_roles.update(expected_roles)

        allowed_direct_roles = set(expected.get("allowed_direct_roles") or ())
        direct_allowed = expected.get("direct_to_master_allowed") is True
        if direct_to_master and not direct_allowed:
            findings.append(
                _finding(
                    "template.source_direct_to_master",
                    _template_severity("high", confidence, options),
                    "Source Routes Directly To Master",
                    "A source channel routes directly to Master although the template "
                    "expects a bus or premaster path. This may be intentional, "
                    "but should be reviewed.",
                    [_template_channel_item(channel, target, track_by_index, source_role)],
                )
            )
            bypasses += 1
            if _signal_active(signal_flow, target) and _signal_active(signal_flow, 0):
                signal_findings.append(
                    _finding(
                        "template.source_bypass_signal_confirmed",
                        "high",
                        "Template Bus Bypass Confirmed By Signal",
                        "Playback evidence confirms activity on a direct-to-master source path.",
                        [_template_channel_item(channel, target, track_by_index, source_role)],
                        signal_flow=signal_flow,
                    )
                )
        elif expected_roles and not (path_roles & expected_roles):
            if not (path_roles & allowed_direct_roles):
                findings.append(
                    _finding(
                        "template.source_bypasses_expected_bus",
                        _template_severity("medium", confidence, options),
                        "Source Bypasses Expected Template Bus",
                        "A source channel appears to bypass its expected role bus. "
                        "This may be intentional, but does not match the selected "
                        "routing template.",
                        [_template_channel_item(channel, target, track_by_index, source_role)],
                    )
                )
                bypasses += 1

        if signal_flow and signal_flow.get("available") and _signal_active(signal_flow, target):
            expected_role_tracks = _tracks_matching_roles(expected_roles, role_by_track)
            silent_expected_tracks = [
                track
                for track in expected_role_tracks
                if track != target and not _signal_active(signal_flow, track)
            ]
            for expected_track in silent_expected_tracks:
                key = (_channel_index(channel) or -1, expected_track)
                if key in reported_expected_bus_silent:
                    continue
                reported_expected_bus_silent.add(key)
                item = _template_channel_item(channel, target, track_by_index, source_role)
                item.update(
                    {
                        "expected_bus_track": expected_track,
                        "expected_bus_name": (track_by_index.get(expected_track) or {}).get("name"),
                    }
                )
                signal_findings.append(
                    _finding(
                        "template.expected_bus_silent_signal_confirmed",
                        "high",
                        "Expected Template Bus Silent During Playback",
                        "Playback evidence shows source activity while an expected "
                        "template bus remains silent.",
                        [item],
                        signal_flow=signal_flow,
                    )
                )
            if (
                "master" in {str(role) for role in expected.get("expected_path") or ()}
                and not _signal_active(signal_flow, 0)
                and target not in reported_master_path_missing
            ):
                reported_master_path_missing.add(target)
                signal_findings.append(
                    _finding(
                        "template.master_path_missing_signal_confirmed",
                        "critical",
                        "Expected Master Path Silent During Playback",
                        "Playback evidence suggests an active source does not reach "
                        "the expected premaster/master path.",
                        [_template_channel_item(channel, target, track_by_index, source_role)],
                        signal_flow=signal_flow,
                    )
                )

    for role in sorted(_always_expected_roles(expected_by_source, source_roles_present)):
        if not _roles_available({role}, role_by_track):
            missing_roles.add(role)

    for role in sorted(missing_roles):
        findings.append(
            _finding(
                "template.premaster_missing"
                if role == "premaster"
                else "template.expected_bus_missing",
                _template_severity(
                    "high" if role == "premaster" else "medium", confidence, options
                ),
                "Expected Template Bus Missing" if role != "premaster" else "Premaster Missing",
                (
                    "The selected or detected template expects a premaster or mix bus "
                    "before Master, but none was found."
                    if role == "premaster"
                    else (
                        "The selected or detected template expects a "
                        f"{role.replace('_', ' ')} role, but no matching mixer track "
                        "was found."
                    )
                ),
                [{"expected_template_role": role, "template_profile_id": summary["profile_id"]}],
            )
        )

    for track, roles in sorted(role_by_track.items()):
        bus_roles = roles & {
            "premaster",
            "stem_bus",
            "kick_bus",
            "drum_bus",
            "bass_bus",
            "lowend_bus",
            "synth_bus",
            "fx_bus",
            "vocal_bus",
        }
        if not bus_roles:
            continue
        reachable = _reachable_tracks(track, routes_by_src)
        if track != 0 and 0 not in reachable:
            findings.append(
                _finding(
                    "template.bus_without_master_path",
                    _template_severity("critical", confidence, options),
                    "Template Bus Has No Master Path",
                    "A required bus exists but appears to have no valid path to Master "
                    "or hardware output.",
                    [_template_track_item(track, track_by_index, next(iter(bus_roles)))],
                )
            )
        if not incoming_by_dst.get(track):
            findings.append(
                _finding(
                    "template.bus_has_no_sources",
                    _template_severity("low", confidence, options),
                    "Template Bus Has No Sources",
                    "A template bus exists but appears to receive no source channels or sends.",
                    [_template_track_item(track, track_by_index, next(iter(bus_roles)))],
                )
            )
        if signal_flow and _signal_active(signal_flow, track) and 0 not in reachable:
            signal_findings.append(
                _finding(
                    "template.bus_without_output_signal_confirmed",
                    "critical",
                    "Active Template Bus Has No Output Signal Path",
                    "Playback evidence suggests that a bus receives signal but does not "
                    "pass signal to its expected downstream route.",
                    [_template_track_item(track, track_by_index, next(iter(bus_roles)))],
                    signal_flow=signal_flow,
                )
            )

    summary["missing_expected_roles"] = sorted(missing_roles)
    summary["bypasses_detected"] = bypasses
    summary["reference_or_sidechain_risks"] = reference_risks
    summary["compliance_status"] = (
        "needs_review" if missing_roles or bypasses or reference_risks else "ok"
    )
    if signal_flow and signal_flow.get("available"):
        findings.extend(signal_findings)
    return {
        "enabled": True,
        "findings": findings,
        "summary": summary,
        "profile": selected_profile,
    }


def level_2_signal_findings(
    *,
    channels: list[dict[str, Any]],
    routing: list[dict[str, Any]],
    mixer_tracks: list[dict[str, Any]],
    signal_flow: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    if not signal_flow or not signal_flow.get("available"):
        return [
            _finding(
                "signal_flow_unavailable",
                "info",
                "Signal-Flow Evidence Unavailable",
                "Level 2 could not collect a meter snapshot. Run Level 1 or retry "
                "Level 2 after setting playback/loop evidence.",
                [],
            )
        ]
    track_by_index, routes_by_src, _incoming = _routing_maps(routing, mixer_tracks)
    findings: list[dict[str, Any]] = []
    master_active = _signal_active(signal_flow, 0)
    any_meter_active = master_active or any(
        _signal_active(signal_flow, track) for track in track_by_index
    )
    for channel in channels:
        target = _as_int(channel.get("target_mixer_track"))
        if target in (None, 0):
            continue
        channel_muted = _as_bool(channel.get("mute")) is True
        target_active = _signal_active(signal_flow, target)
        routes_to_master = any(
            _as_int(route.get("dst")) == 0 for route in routes_by_src.get(target, ())
        )
        if any_meter_active and _channel_static_active(channel) and not target_active:
            findings.append(
                _finding(
                    "channel_active_mixer_silent",
                    "high",
                    "Channel Active But Mixer Track Silent",
                    "The Channel Rack item appears active, but the assigned Mixer Track "
                    "shows no meter activity during playback.",
                    [
                        _template_channel_item(
                            channel, target, track_by_index, _source_role(channel)
                        )
                    ],
                    signal_flow=signal_flow,
                )
            )
        if channel_muted and target_active:
            findings.append(
                _finding(
                    "mixer_active_despite_channel_mute",
                    "high",
                    "Mixer Active Despite Channel Mute",
                    "The Channel Rack item is muted, but the assigned Mixer Track shows "
                    "signal activity during playback.",
                    [
                        _template_channel_item(
                            channel, target, track_by_index, _source_role(channel)
                        )
                    ],
                    signal_flow=signal_flow,
                )
            )
        if target_active and routes_to_master and master_active:
            findings.append(
                _finding(
                    "direct_to_master_signal_confirmed",
                    "high",
                    "Direct-To-Master Signal Confirmed",
                    "A generator routes directly to Master and playback evidence confirms "
                    "signal activity on the source and Master.",
                    [
                        _template_channel_item(
                            channel, target, track_by_index, _source_role(channel)
                        )
                    ],
                    signal_flow=signal_flow,
                )
            )
    return findings


def template_status_payload(
    *,
    template_context: dict[str, Any],
    options: RoutingAuditOptions,
    compliance_summary: dict[str, Any] | None = None,
) -> dict[str, Any]:
    compact = templates.compact_context(template_context) or {}
    profile = _selected_profile(compact, options)
    summary = dict(compliance_summary or {})
    return {
        "detected_template_profile": compact.get("template_slug"),
        "detected_template_name": compact.get("template_name"),
        "selected_template_profile": options.selected_template_profile,
        "display_name": summary.get("display_name")
        or (profile.get("template_name") if profile else compact.get("template_name")),
        "confidence": summary.get("confidence") or _template_confidence(compact, options, profile),
        "profile_source": summary.get("profile_source")
        or _profile_source(compact, options, profile),
        "template_compliance": options.template_compliance,
    }


def _selected_profile(
    compact_context: dict[str, Any],
    options: RoutingAuditOptions,
) -> dict[str, Any] | None:
    if options.template_compliance == TEMPLATE_COMPLIANCE_OFF:
        return None
    if options.template_compliance == TEMPLATE_COMPLIANCE_MANUAL:
        return templates.profile_by_slug(options.selected_template_profile)
    if not compact_context.get("template_slug") or compact_context.get("ambiguous"):
        return None
    confidence = _template_confidence(compact_context, options, None)
    if confidence == "low":
        return None
    return templates.profile_by_slug(compact_context.get("template_slug"))


def _profile_source(
    compact_context: dict[str, Any],
    options: RoutingAuditOptions,
    profile: dict[str, Any] | None,
) -> str:
    if options.template_compliance == TEMPLATE_COMPLIANCE_OFF:
        return "off"
    if options.template_compliance == TEMPLATE_COMPLIANCE_MANUAL:
        return "manual_select" if profile else "manual_select_unavailable"
    return "auto_detect" if profile else "auto_detect_unavailable"


def _template_confidence(
    compact_context: dict[str, Any],
    options: RoutingAuditOptions,
    profile: dict[str, Any] | None,
) -> str:
    if options.template_compliance == TEMPLATE_COMPLIANCE_OFF:
        return "off"
    if options.template_compliance == TEMPLATE_COMPLIANCE_MANUAL:
        return "manual" if profile else "low"
    raw = str(compact_context.get("confidence_level") or "").strip().lower()
    if compact_context.get("ambiguous"):
        return "low"
    if raw in {"implementation_verified", "cross_platform_verified", "measured_repeated", "high"}:
        return "high"
    if raw in {"measured_once", "docs_confirmed", "user_reported", "medium"}:
        return "medium"
    return "low"


def _template_severity(
    severity: str,
    confidence: str,
    options: RoutingAuditOptions,
) -> str:
    if options.template_compliance == TEMPLATE_COMPLIANCE_MANUAL:
        return severity
    if confidence == "low" and severity in {"high", "critical"}:
        return "medium"
    if confidence == "medium" and severity == "critical":
        return "high"
    return severity


def _expected_paths_by_source(profile: dict[str, Any]) -> dict[str, dict[str, Any]]:
    rows = profile.get("expected_paths")
    if not isinstance(rows, list) or not rows:
        rows = list(_DEFAULT_EXPECTED_PATHS)
    out: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        source_role = _canonical_source_role(str(row.get("source_role") or ""))
        if not source_role:
            continue
        out[source_role] = dict(row)
    return out


def _canonical_source_role(value: str) -> str | None:
    normalized = value.strip().lower()
    aliases = {
        "kick_and_bass_group": "bass",
        "percussion_or_hats": "drums_or_percussion",
        "leads_arps_acids": "synth_lead_arp_pad",
        "pads_atmospheres": "synth_lead_arp_pad",
        "fx_returns": "fx_return",
        "reference_track": "reference",
        "sidechain_trigger": "sidechain_control",
    }
    if normalized in _SOURCE_ROLE_ALIASES:
        return normalized
    return aliases.get(normalized)


def _expected_bus_role_candidates(expected: dict[str, Any]) -> set[str]:
    roles: set[str] = set()
    for item in expected.get("expected_path") or ():
        roles.update(_EXPECTED_ROLE_GROUPS.get(str(item), {str(item)}))
    roles.discard("master")
    roles.discard("sidechain_control")
    roles.discard("reference")
    roles.discard("print_or_render")
    return roles


def _always_expected_roles(
    expected_by_source: dict[str, dict[str, Any]],
    source_roles_present: set[str],
) -> set[str]:
    roles: set[str] = set()
    for source_role in source_roles_present:
        expected = expected_by_source.get(source_role) or {}
        if "premaster" in expected.get("expected_path", ()):
            roles.add("premaster")
    return roles


def _role_map(
    profile: dict[str, Any],
    template_context: dict[str, Any],
    name_by_track: dict[int, Any],
) -> dict[int, set[str]]:
    aliases = _profile_role_aliases(profile)
    roles: dict[int, set[str]] = {}
    for track, name in name_by_track.items():
        track_roles = set()
        template_role = templates.role_for(template_context, track)
        if template_role == templates.ROLE_PREMASTER:
            track_roles.add("premaster")
        elif template_role == templates.ROLE_MASTER:
            track_roles.add("master")
        elif template_role == templates.ROLE_STEM_BUS:
            track_roles.add(_bus_role_from_name(name))
            track_roles.add("stem_bus")
        elif template_role == templates.ROLE_SIDECHAIN_CONTROL:
            track_roles.add("sidechain_control")
        elif template_role == templates.ROLE_RESERVED_PLACEHOLDER:
            track_roles.add("template_reserved_placeholder")
        text = _name_text(name)
        for role, values in aliases.items():
            if any(alias in text for alias in values):
                track_roles.add(role)
        if track == 0:
            track_roles.add("master")
        roles[track] = {role for role in track_roles if role}
    return roles


def _profile_role_aliases(profile: dict[str, Any]) -> dict[str, tuple[str, ...]]:
    aliases: dict[str, list[str]] = {
        role: list(values) for role, values in _DEFAULT_ROLE_ALIASES.items()
    }
    extra = profile.get("track_role_aliases")
    if isinstance(extra, dict):
        for role, values in extra.items():
            if isinstance(values, list):
                aliases.setdefault(str(role), []).extend(str(value) for value in values)
    for row in profile.get("mixer_tracks") or ():
        if not isinstance(row, dict):
            continue
        role = str(row.get("role") or "")
        name = str(row.get("name") or "")
        if not name:
            continue
        if role == "premaster":
            aliases.setdefault("premaster", []).append(name)
        elif role == "master":
            aliases.setdefault("master", []).append(name)
        elif role == "sidechain_control":
            aliases.setdefault("sidechain_control", []).append(name)
        elif role == "reserved_placeholder":
            aliases.setdefault("template_reserved_placeholder", []).append(name)
        elif role in {"stem_bus", "source", "utility"}:
            aliases.setdefault(_bus_role_from_name(name), []).append(name)
    return {
        role: tuple(dict.fromkeys(_name_text(value) for value in values if _name_text(value)))
        for role, values in aliases.items()
    }


def _source_role(channel: dict[str, Any]) -> str | None:
    text = _name_text(
        " ".join(str(channel.get(key) or "") for key in ("name", "target_name", "source_role"))
    )
    for role, aliases in _SOURCE_ROLE_ALIASES.items():
        if any(alias in text for alias in aliases):
            return role
    return None


def _bus_role_from_name(name: Any) -> str:
    text = _name_text(name)
    if any(token in text for token in ("kick",)):
        return "kick_bus"
    if any(token in text for token in ("bass", "sub", "lowend", "low-end")):
        return "bass_bus"
    if any(token in text for token in ("drum", "perc", "hat", "snare", "overhead")):
        return "drum_bus"
    if any(token in text for token in ("vocal", "vox")):
        return "vocal_bus"
    if any(token in text for token in ("fx", "send", "return", "reverb", "delay")):
        return "fx_bus"
    if any(token in text for token in ("synth", "lead", "instrument", "music", "pad")):
        return "synth_bus"
    return "stem_bus"


def _routing_maps(
    routing: list[dict[str, Any]],
    mixer_tracks: list[dict[str, Any]],
) -> tuple[dict[int, dict[str, Any]], dict[int, list[dict[str, Any]]], dict[int, list[int]]]:
    track_by_index: dict[int, dict[str, Any]] = {}
    for row in mixer_tracks:
        idx = _track_index(row)
        if idx is not None:
            track_by_index[idx] = dict(row)
    for row in routing:
        idx = _track_index(row)
        if idx is None:
            continue
        merged = {**track_by_index.get(idx, {}), **dict(row)}
        track_by_index[idx] = merged
    routes_by_src: dict[int, list[dict[str, Any]]] = {}
    incoming_by_dst: dict[int, list[int]] = {}
    for idx, row in track_by_index.items():
        routes = _normalise_routes(row.get("routes_to") or [])
        routes_by_src[idx] = routes
        for route in routes:
            dst = _as_int(route.get("dst"))
            if dst is not None:
                incoming_by_dst.setdefault(dst, []).append(idx)
    return track_by_index, routes_by_src, incoming_by_dst


def _normalise_routes(routes: list[Any]) -> list[dict[str, Any]]:
    out = []
    for route in routes:
        if isinstance(route, dict):
            dst = _as_int(route.get("dst", route.get("target")))
            if dst is not None:
                out.append(
                    {
                        "dst": dst,
                        "dst_name": route.get("dst_name") or route.get("target_name"),
                        "level": route.get("level"),
                    }
                )
        else:
            dst = _as_int(route)
            if dst is not None:
                out.append({"dst": dst, "dst_name": None, "level": None})
    return out


def _reachable_tracks(start: int, routes_by_src: dict[int, list[dict[str, Any]]]) -> set[int]:
    seen: set[int] = set()
    stack = [start]
    while stack:
        src = stack.pop()
        if src in seen:
            continue
        seen.add(src)
        for route in routes_by_src.get(src, ()):
            dst = _as_int(route.get("dst"))
            if dst is not None and dst not in seen:
                stack.append(dst)
    return seen


def _path_roles(path_tracks: set[int], role_by_track: dict[int, set[str]]) -> set[str]:
    roles: set[str] = set()
    for track in path_tracks:
        roles.update(role_by_track.get(track, set()))
    return roles


def _roles_available(expected_roles: set[str], role_by_track: dict[int, set[str]]) -> bool:
    return any(roles & expected_roles for roles in role_by_track.values())


def _tracks_matching_roles(
    expected_roles: set[str],
    role_by_track: dict[int, set[str]],
) -> list[int]:
    return sorted(
        track
        for track, roles in role_by_track.items()
        if track != 0 and bool(roles & expected_roles)
    )


def _signal_active(signal_flow: dict[str, Any] | None, track: int | None) -> bool:
    if not signal_flow or not signal_flow.get("available") or track is None:
        return False
    peaks = signal_flow.get("track_peaks") or {}
    peak = _as_float(peaks.get(str(track), peaks.get(track)))
    threshold = _as_float(signal_flow.get("active_threshold")) or 0.00001
    return peak is not None and peak >= threshold


def _channel_static_active(channel: dict[str, Any]) -> bool:
    if _as_bool(channel.get("mute")) is True:
        return False
    volume = _as_float(channel.get("vol_norm"))
    if volume is None:
        return False
    return volume > 0.05


def _finding(
    rule_id: str,
    severity: str,
    title: str,
    detail: str,
    items: list[dict[str, Any]],
    *,
    signal_flow: dict[str, Any] | None = None,
) -> dict[str, Any]:
    row = {
        "id": rule_id,
        "severity": severity,
        "title": title,
        "detail": detail,
        "count": len(items),
        "items": items[:12],
    }
    if signal_flow:
        row["metadata"] = {
            "evidence_type": "live_meter_window",
            "signal_flow": {
                "available": signal_flow.get("available"),
                "playback_used": signal_flow.get("playback_used"),
                "marker_name": signal_flow.get("marker_name"),
                "loop_duration_seconds": signal_flow.get("loop_duration_seconds"),
            },
        }
    return row


def _comparison_item(channel: dict[str, Any], track: dict[str, Any], target: int) -> dict[str, Any]:
    return {
        "channel": _channel_index(channel),
        "channel_name": channel.get("name"),
        "name": channel.get("name"),
        "mixer_track": target,
        "mixer_name": track.get("name") or channel.get("target_name"),
    }


def _template_channel_item(
    channel: dict[str, Any],
    target: int,
    track_by_index: dict[int, dict[str, Any]],
    source_role: str | None,
) -> dict[str, Any]:
    return {
        "channel": _channel_index(channel),
        "channel_name": channel.get("name"),
        "name": channel.get("name"),
        "mixer_track": target,
        "mixer_name": (track_by_index.get(target) or {}).get("name") or channel.get("target_name"),
        "source_role": source_role,
    }


def _template_track_item(
    track: int,
    track_by_index: dict[int, dict[str, Any]],
    role: str,
) -> dict[str, Any]:
    return {
        "track": track,
        "mixer_track": track,
        "mixer_name": (track_by_index.get(track) or {}).get("name"),
        "expected_template_role": role,
    }


def _channel_index(row: dict[str, Any]) -> int | None:
    return _as_int(row.get("channel", row.get("i", row.get("index"))))


def _track_index(row: dict[str, Any]) -> int | None:
    return _as_int(row.get("i", row.get("index", row.get("track"))))


def _name_text(value: Any) -> str:
    return str(value or "").strip().lower()


def _near_silent(value: float) -> bool:
    return value <= 0.05


def _as_int(value: Any) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _as_float(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _as_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if value is None:
        return None
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "1", "yes", "on"}:
            return True
        if normalized in {"false", "0", "no", "off"}:
            return False
    return None

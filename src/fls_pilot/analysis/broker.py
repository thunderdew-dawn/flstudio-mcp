"""Read-only analysis broker for reusable project observations."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any

from .. import project_templates as templates
from .canonical import mixer_count_policy, pattern_count_policy, playlist_count_policy
from .fl_reads import (
    PLAYLIST_TRACKS_SPEC,
    STATIC_INVALIDATION_EVENTS,
    STATIC_PAGED_READS,
    StaticReadSpec,
    payload_rows,
    project_fingerprint,
    read_paged_resource,
    read_project_state,
)
from .live import (
    LiveMeterPolicy,
    LiveMeterWindow,
    WatcherProvider,
    normalize_live_meter_window,
)
from .observations import Observation, ObservationStore
from .schema import Coverage


@dataclass(frozen=True)
class StaticSnapshotPolicy:
    ttl_seconds: float = 60.0
    connection_ttl_seconds: float = 2.0
    force_refresh: bool = False
    include_patterns: bool = True
    include_playlist: bool = True
    page_timeout: float | None = None
    page_attempts: int = 1


@dataclass(frozen=True)
class StaticProjectSnapshot:
    created_at: float
    project_fingerprint: str
    project_state: dict[str, Any] = field(default_factory=dict)
    channels: tuple[dict[str, Any], ...] = ()
    mixer_tracks: tuple[dict[str, Any], ...] = ()
    routing: tuple[dict[str, Any], ...] = ()
    patterns: tuple[dict[str, Any], ...] = ()
    playlist_tracks: tuple[dict[str, Any], ...] = ()
    template_context: dict[str, Any] = field(default_factory=dict)
    counts: dict[str, Any] = field(default_factory=dict)
    coverage: Coverage = field(default_factory=Coverage)
    source_observation_ids: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)
    observation_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "created_at": self.created_at,
            "project_fingerprint": self.project_fingerprint,
            "project_state": dict(self.project_state),
            "channels": [dict(row) for row in self.channels],
            "mixer_tracks": [dict(row) for row in self.mixer_tracks],
            "routing": [dict(row) for row in self.routing],
            "patterns": [dict(row) for row in self.patterns],
            "playlist_tracks": [dict(row) for row in self.playlist_tracks],
            "template_context": dict(self.template_context),
            "counts": dict(self.counts),
            "coverage": self.coverage.to_dict(),
            "source_observation_ids": list(self.source_observation_ids),
            "errors": list(self.errors),
            "metadata": dict(self.metadata),
        }
        if self.observation_id:
            out["observation_id"] = self.observation_id
        return out

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> StaticProjectSnapshot:
        coverage = payload.get("coverage") if isinstance(payload.get("coverage"), dict) else {}
        return cls(
            observation_id=payload.get("observation_id"),
            created_at=float(payload.get("created_at") or 0.0),
            project_fingerprint=str(payload.get("project_fingerprint") or "unknown"),
            project_state=dict(payload.get("project_state") or {}),
            channels=tuple(dict(row) for row in payload.get("channels") or []),
            mixer_tracks=tuple(dict(row) for row in payload.get("mixer_tracks") or []),
            routing=tuple(dict(row) for row in payload.get("routing") or []),
            patterns=tuple(dict(row) for row in payload.get("patterns") or []),
            playlist_tracks=tuple(dict(row) for row in payload.get("playlist_tracks") or []),
            template_context=dict(payload.get("template_context") or {}),
            counts=dict(payload.get("counts") or {}),
            coverage=Coverage(
                required=coverage.get("required", 0),
                available=coverage.get("available", 0),
                missing=tuple(coverage.get("missing") or ()),
                optional_available=coverage.get("optional_available", 0),
            ),
            source_observation_ids=tuple(payload.get("source_observation_ids") or ()),
            errors=tuple(payload.get("errors") or ()),
            metadata=dict(payload.get("metadata") or {}),
        )


class AnalysisBroker:
    """Collect and reuse read-only observations across workflow analyzers."""

    def __init__(
        self,
        *,
        observation_store: ObservationStore | None = None,
        source: str = "analysis_broker",
    ) -> None:
        self.observation_store = observation_store or ObservationStore()
        self.source = source

    def get_static_project_snapshot(
        self,
        bridge: Any,
        policy: StaticSnapshotPolicy | None = None,
    ) -> StaticProjectSnapshot:
        policy = policy or StaticSnapshotPolicy()
        if not policy.force_refresh:
            cached = self.observation_store.latest("static_project_snapshot")
            if cached is not None and isinstance(cached.payload, dict):
                snapshot = StaticProjectSnapshot.from_dict(cached.payload)
                return replace(snapshot, observation_id=cached.observation_id)
        return self._collect_static_project_snapshot(bridge, policy)

    def get_live_meter_window(
        self,
        bridge: Any,
        policy: LiveMeterPolicy | None = None,
        watcher_provider: WatcherProvider | None = None,
    ) -> LiveMeterWindow:
        policy = policy or LiveMeterPolicy()
        
        # Read minimal project state for playing status and fingerprint context
        project_obs = self._record_project_state(bridge, StaticSnapshotPolicy(ttl_seconds=policy.ttl_seconds))
        project_state = _payload_dict(project_obs.payload)
        fingerprint = project_fingerprint(project_state)
        
        status = watcher_provider.status() if watcher_provider else None
        last_max = watcher_provider.last_max() if watcher_provider else None
        
        window = normalize_live_meter_window(
            status=status,
            last_max=last_max,
            project_state=project_state,
            policy=policy,
            project_fingerprint=fingerprint,
        )
        
        self.observation_store.record(
            kind="live_meter_window",
            payload=window.to_dict(),
            source=self.source,
            ttl_seconds=policy.ttl_seconds,
            confidence=window.confidence,
            project_fingerprint=fingerprint,
            invalidates_on=(),
            errors=window.errors,
        )
        return window

    def _collect_static_project_snapshot(
        self,
        bridge: Any,
        policy: StaticSnapshotPolicy,
    ) -> StaticProjectSnapshot:
        session_observation = self._record_session_alive(bridge, policy)
        project_observation = self._record_project_state(bridge, policy)
        resource_observations = [
            self._record_paged_resource(bridge, spec, policy)
            for spec in self._included_specs(policy)
        ]

        observations = [session_observation, project_observation, *resource_observations]
        by_kind = {observation.kind: observation for observation in observations}
        project_state = _payload_dict(project_observation.payload)
        channels = tuple(
            payload_rows(_payload_for(by_kind, "channel_routing_snapshot"), "channels")
        )
        mixer_tracks = tuple(payload_rows(_payload_for(by_kind, "mixer_tracks_snapshot"), "tracks"))
        routing = tuple(payload_rows(_payload_for(by_kind, "routing_snapshot"), "routing"))
        patterns = tuple(payload_rows(_payload_for(by_kind, "patterns_snapshot"), "patterns"))
        playlist_tracks = tuple(
            payload_rows(_payload_for(by_kind, "playlist_tracks_snapshot"), "tracks")
        )
        template_context = templates.classify_topology(mixer_tracks or routing, routing, channels)
        annotated_mixer_tracks = tuple(templates.annotate_tracks(mixer_tracks, template_context))
        counts = _snapshot_counts(
            project_state=project_state,
            channels=channels,
            mixer_tracks=annotated_mixer_tracks,
            patterns=patterns,
            playlist_tracks=playlist_tracks,
            routing=routing,
        )
        fingerprint = project_fingerprint(project_state, counts=_fingerprint_counts(counts))
        coverage = _coverage_for(observations, self._included_specs(policy))
        errors = _observation_errors(observations)
        template_observation = self.observation_store.record(
            kind="template_context_snapshot",
            payload=template_context,
            source=self.source,
            ttl_seconds=policy.ttl_seconds,
            confidence="implementation_verified",
            project_fingerprint=fingerprint,
            invalidates_on=STATIC_INVALIDATION_EVENTS,
            metadata={"source_observation_ids": [row.observation_id for row in observations]},
        )
        observations.append(template_observation)
        source_observation_ids = tuple(row.observation_id for row in observations)
        snapshot = StaticProjectSnapshot(
            created_at=self.observation_store.now(),
            project_fingerprint=fingerprint,
            project_state=project_state,
            channels=channels,
            mixer_tracks=annotated_mixer_tracks,
            routing=routing,
            patterns=patterns,
            playlist_tracks=playlist_tracks,
            template_context=template_context,
            counts=counts,
            coverage=coverage,
            source_observation_ids=source_observation_ids,
            errors=errors,
            metadata={
                "policy": {
                    "ttl_seconds": policy.ttl_seconds,
                    "include_patterns": policy.include_patterns,
                    "include_playlist": policy.include_playlist,
                    "force_refresh": policy.force_refresh,
                }
            },
        )
        snapshot_observation = self.observation_store.record(
            kind="static_project_snapshot",
            payload=snapshot.to_dict(),
            source=self.source,
            ttl_seconds=policy.ttl_seconds,
            confidence="implementation_verified",
            project_fingerprint=fingerprint,
            invalidates_on=STATIC_INVALIDATION_EVENTS,
            errors=errors,
        )
        return replace(snapshot, observation_id=snapshot_observation.observation_id)

    def _record_session_alive(
        self,
        bridge: Any,
        policy: StaticSnapshotPolicy,
    ) -> Observation:
        errors: list[str] = []
        alive: bool | None = None
        heartbeat_age: float | None = None
        try:
            is_alive = getattr(bridge, "is_alive", None)
            if callable(is_alive):
                alive = bool(is_alive())
        except Exception as exc:
            errors.append(f"is_alive -> {type(exc).__name__}: {exc}")
        try:
            get_age = getattr(bridge, "heartbeat_age", None)
            if callable(get_age):
                age = get_age()
                heartbeat_age = float(age) if isinstance(age, (int, float)) else None
        except Exception as exc:
            errors.append(f"heartbeat_age -> {type(exc).__name__}: {exc}")

        payload: dict[str, Any] = {"alive": alive, "heartbeat_age": heartbeat_age}
        if alive is False:
            errors.append("bridge heartbeat is not alive")
        return self.observation_store.record(
            kind="fl_session_alive",
            payload=payload,
            source=self.source,
            ttl_seconds=policy.connection_ttl_seconds,
            confidence="runtime_reported" if alive is not None else "unknown",
            invalidates_on=("fl_disconnect",),
            errors=errors,
        )

    def _record_project_state(
        self,
        bridge: Any,
        policy: StaticSnapshotPolicy,
    ) -> Observation:
        payload: dict[str, Any] = {}
        errors: list[str] = []
        try:
            payload = read_project_state(bridge)
        except Exception as exc:
            errors.append(f"project_state -> {type(exc).__name__}: {exc}")
        return self.observation_store.record(
            kind="project_state",
            payload=payload,
            source=self.source,
            ttl_seconds=policy.ttl_seconds,
            confidence="implementation_verified" if not errors else "unknown",
            invalidates_on=STATIC_INVALIDATION_EVENTS,
            errors=errors,
        )

    def _record_paged_resource(
        self,
        bridge: Any,
        spec: StaticReadSpec,
        policy: StaticSnapshotPolicy,
    ) -> Observation:
        payload: dict[str, Any] = {}
        errors: list[str] = []
        try:
            payload = read_paged_resource(
                bridge,
                spec,
                timeout=policy.page_timeout,
                attempts=policy.page_attempts,
            )
        except Exception as exc:
            errors.append(f"{spec.command} -> {type(exc).__name__}: {exc}")
        return self.observation_store.record(
            kind=spec.kind,
            payload=payload,
            source=self.source,
            ttl_seconds=spec.ttl_seconds,
            confidence="implementation_verified" if not errors else "unknown",
            invalidates_on=STATIC_INVALIDATION_EVENTS,
            errors=errors,
        )

    @staticmethod
    def _included_specs(policy: StaticSnapshotPolicy) -> tuple[StaticReadSpec, ...]:
        specs = []
        for spec in STATIC_PAGED_READS:
            if spec.kind == "patterns_snapshot" and not policy.include_patterns:
                continue
            if spec.kind == PLAYLIST_TRACKS_SPEC.kind and not policy.include_playlist:
                continue
            specs.append(spec)
        return tuple(specs)


def _payload_dict(payload: Any) -> dict[str, Any]:
    return dict(payload) if isinstance(payload, dict) else {}


def _payload_for(observations: dict[str, Observation], kind: str) -> dict[str, Any]:
    observation = observations.get(kind)
    return _payload_dict(observation.payload) if observation else {}


def _coverage_for(
    observations: list[Observation],
    specs: tuple[StaticReadSpec, ...],
) -> Coverage:
    now = max((row.created_at for row in observations), default=0.0)
    required_kinds = {"project_state", *(spec.kind for spec in specs if spec.required)}
    optional_kinds = {spec.kind for spec in specs if not spec.required}
    by_kind = {row.kind: row for row in observations}
    available = sum(
        1
        for kind in required_kinds
        if (observation := by_kind.get(kind)) is not None and observation.is_usable(now)
    )
    optional_available = sum(
        1
        for kind in optional_kinds
        if (observation := by_kind.get(kind)) is not None and observation.is_usable(now)
    )
    missing = []
    for kind in sorted(required_kinds | optional_kinds):
        observation = by_kind.get(kind)
        if observation is None or not observation.is_usable(now):
            missing.append(kind)
    return Coverage(
        required=len(required_kinds),
        available=available,
        missing=tuple(missing),
        optional_available=optional_available,
    )


def _observation_errors(observations: list[Observation]) -> tuple[str, ...]:
    errors = []
    for observation in observations:
        errors.extend(f"{observation.kind}: {error}" for error in observation.errors)
    return tuple(errors)


def _snapshot_counts(
    *,
    project_state: dict[str, Any],
    channels: tuple[dict[str, Any], ...],
    mixer_tracks: tuple[dict[str, Any], ...],
    patterns: tuple[dict[str, Any], ...],
    playlist_tracks: tuple[dict[str, Any], ...],
    routing: tuple[dict[str, Any], ...],
) -> dict[str, Any]:
    pattern_count = _int_or_len(project_state.get("pattern_count"), patterns)
    mixer_count = _int_or_len(project_state.get("mixer_track_count"), mixer_tracks)
    return {
        "channels": len(channels),
        "routing_rows": len(routing),
        "mixer": mixer_count_policy(mixer_count),
        "patterns": pattern_count_policy(pattern_count),
        "playlist": playlist_count_policy(
            used_tracks=_int_or_len(project_state.get("playlist_track_count"), playlist_tracks)
        ),
    }


def _fingerprint_counts(counts: dict[str, Any]) -> dict[str, Any]:
    return {
        "channels": counts.get("channels"),
        "routing_rows": counts.get("routing_rows"),
        "mixer_api_slots": (counts.get("mixer") or {}).get("api_slots"),
        "pattern_api_count": (counts.get("patterns") or {}).get("api_count"),
        "playlist_used_tracks": (counts.get("playlist") or {}).get("used_tracks"),
    }


def _int_or_len(value: Any, rows: tuple[dict[str, Any], ...]) -> int:
    try:
        if value is not None:
            return max(0, int(value))
    except (TypeError, ValueError):
        pass
    return len(rows)

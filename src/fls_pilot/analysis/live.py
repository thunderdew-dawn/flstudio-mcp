"""Live runtime observation helpers and schemas."""

from __future__ import annotations

from dataclasses import dataclass, field
from time import time
from typing import Any, Protocol

from .schema import Coverage


@dataclass(frozen=True)
class LiveMeterPolicy:
    ttl_seconds: float = 2.0
    require_playing: bool = False
    min_capture_seconds: float = 1.0
    recent_watch_seconds: float = 120.0


class WatcherProvider(Protocol):
    def status(self) -> dict[str, Any]: ...

    def last_max(self) -> dict[int, float]: ...


@dataclass(frozen=True)
class LiveMeterWindow:
    target_capture_seconds: float
    captured_seconds: float
    read_count: int
    watched_track_count: int
    playback_state: str
    started_at: float | None = None
    completed_at: float | None = None
    created_at: float = field(default_factory=time)
    track_meter_summaries: dict[str, Any] = field(default_factory=dict)
    source: str = "peak_watcher"
    project_fingerprint: str | None = None
    freshness: str = "unknown"
    coverage: Coverage = field(default_factory=Coverage)
    confidence: str = "unknown"
    errors: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        out = {
            "target_capture_seconds": self.target_capture_seconds,
            "captured_seconds": self.captured_seconds,
            "read_count": self.read_count,
            "watched_track_count": self.watched_track_count,
            "playback_state": self.playback_state,
            "created_at": self.created_at,
            "track_meter_summaries": self.track_meter_summaries,
            "source": self.source,
            "freshness": self.freshness,
            "coverage": self.coverage.to_dict(),
            "confidence": self.confidence,
            "errors": list(self.errors),
            "limitations": list(self.limitations),
        }
        if self.started_at is not None:
            out["started_at"] = self.started_at
        if self.completed_at is not None:
            out["completed_at"] = self.completed_at
        if self.project_fingerprint:
            out["project_fingerprint"] = self.project_fingerprint
        return out


def normalize_live_meter_window(
    *,
    status: dict[str, Any] | None,
    last_max: dict[int, float] | None,
    project_state: dict[str, Any],
    policy: LiveMeterPolicy,
    project_fingerprint: str | None = None,
) -> LiveMeterWindow:
    now = time()
    playing = bool(project_state.get("playing"))
    playback_state = "playing" if playing else "stopped"
    status = status or {}
    last_max = last_max or {}

    running = bool(status.get("running", False))
    captured = _as_float(status.get("elapsed_s"))
    reads = _as_int(status.get("reads"))
    tracks = _as_int(status.get("tracks"), default=len(last_max))
    started_at = _optional_float(status.get("started_at"))
    completed_at = _optional_float(status.get("completed_at"))
    watch_fingerprint = str(status.get("project_fingerprint") or "") or None

    errors: list[str] = []
    limitations: list[str] = []
    if policy.require_playing and not playing:
        errors.append("playback is stopped")

    fingerprint_mismatch = bool(
        watch_fingerprint and project_fingerprint and watch_fingerprint != project_fingerprint
    )
    if fingerprint_mismatch:
        errors.append("watch belongs to a different project snapshot")

    watch_age = None
    if completed_at is not None:
        watch_age = max(0.0, now - completed_at)
        if watch_age > policy.recent_watch_seconds:
            limitations.append("watch window is stale")

    if captured < policy.min_capture_seconds and (running or last_max):
        limitations.append("short capture window")

    freshness = "fresh"
    confidence = "high"

    if fingerprint_mismatch:
        freshness = "unavailable"
        confidence = "none"
        last_max = {}
    elif not running and not last_max:
        freshness = "unavailable"
        confidence = "none"
        errors.append("no watcher evidence")
    elif watch_age is not None and watch_age > policy.recent_watch_seconds:
        freshness = "stale"
        confidence = "low"
    elif captured < policy.min_capture_seconds:
        freshness = "partial"
        confidence = "low"

    summaries = {str(k): v for k, v in last_max.items()}
    available = int(
        bool(summaries) and captured >= policy.min_capture_seconds and freshness == "fresh"
    )

    return LiveMeterWindow(
        target_capture_seconds=policy.min_capture_seconds,
        captured_seconds=captured,
        read_count=reads,
        watched_track_count=tracks,
        playback_state=playback_state,
        started_at=started_at,
        completed_at=completed_at,
        created_at=now,
        track_meter_summaries=summaries,
        source="peak_watcher",
        project_fingerprint=project_fingerprint,
        freshness=freshness,
        coverage=Coverage(
            required=1,
            available=available,
            missing=() if available else ("recent_live_meter_window",),
        ),
        confidence=confidence,
        errors=tuple(errors),
        limitations=tuple(limitations),
    )


def _as_float(value: Any, *, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _optional_float(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _as_int(value: Any, *, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default

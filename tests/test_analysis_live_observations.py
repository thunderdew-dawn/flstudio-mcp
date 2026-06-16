"""Tests for Phase 6 live runtime observations."""

from fls_pilot.analysis.live import (
    LiveMeterPolicy,
    LiveMeterWindow,
    WatcherProvider,
    normalize_live_meter_window,
)


class FakeWatcher:
    def __init__(self, running=False, elapsed_s=0.0, reads=0, last_max=None):
        self._status = {
            "running": running,
            "elapsed_s": elapsed_s,
            "reads": reads,
            "tracks": len(last_max) if last_max else 0,
        }
        self._last_max = last_max or {}

    def status(self):
        return self._status

    def last_max(self):
        return self._last_max


def test_missing_watcher_yields_unavailable():
    policy = LiveMeterPolicy()
    window = normalize_live_meter_window(
        status=None,
        last_max=None,
        project_state={"playing": True},
        policy=policy,
    )
    assert window.freshness == "unavailable"
    assert window.confidence == "none"
    assert "no watcher evidence" in window.errors


def test_stopped_playback_yields_missing_prerequisite():
    policy = LiveMeterPolicy(require_playing=True)
    window = normalize_live_meter_window(
        status={"running": True, "elapsed_s": 5.0, "reads": 100, "tracks": 10},
        last_max={1: -10.0, 2: -5.0},
        project_state={"playing": False},
        policy=policy,
    )
    assert "playback is stopped" in window.errors
    assert window.playback_state == "stopped"


def test_short_capture_yields_partial_evidence():
    policy = LiveMeterPolicy(min_capture_seconds=2.0)
    watcher = FakeWatcher(running=True, elapsed_s=1.0, reads=10, last_max={1: -12.0})
    window = normalize_live_meter_window(
        status=watcher.status(),
        last_max=watcher.last_max(),
        project_state={"playing": True},
        policy=policy,
    )
    assert "short capture window" in window.limitations
    assert window.freshness == "partial"
    assert window.confidence == "low"
    assert window.coverage.available == 0
    assert window.coverage.required == 1


def test_sufficient_watch_window():
    policy = LiveMeterPolicy(min_capture_seconds=1.0)
    watcher = FakeWatcher(running=True, elapsed_s=5.0, reads=50, last_max={1: -2.0})
    window = normalize_live_meter_window(
        status=watcher.status(),
        last_max=watcher.last_max(),
        project_state={"playing": True},
        policy=policy,
    )
    assert window.freshness == "fresh"
    assert window.confidence == "high"
    assert window.coverage.available == 1
    assert "short capture window" not in window.limitations
    assert not window.errors

from __future__ import annotations

from fls_pilot.analysis import ObservationStore


class FakeClock:
    def __init__(self, value: float = 1000.0) -> None:
        self.value = value

    def __call__(self) -> float:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += seconds


def test_observation_store_returns_fresh_latest_until_ttl_expires() -> None:
    clock = FakeClock()
    store = ObservationStore(clock=clock, max_entries_per_kind=5)

    observation = store.record(
        kind="static_project_snapshot",
        payload={"tracks": 12},
        source="control_center",
        ttl_seconds=30,
        confidence="implementation_verified",
        project_fingerprint="session_a",
        invalidates_on=("fl_disconnect", "project_structure_change"),
    )

    assert observation.freshness_status(clock()) == "fresh"
    assert store.latest("static_project_snapshot", project_fingerprint="session_a") == observation

    clock.advance(31)

    assert observation.freshness_status(clock()) == "stale"
    assert store.latest("static_project_snapshot") is None
    assert store.latest("static_project_snapshot", include_stale=True) == observation


def test_observation_store_invalidation_can_target_events() -> None:
    clock = FakeClock()
    store = ObservationStore(clock=clock)
    static = store.record(
        kind="static_project_snapshot",
        payload={"channels": 4},
        source="broker",
        ttl_seconds=60,
        invalidates_on=("project_structure_change",),
    )
    live = store.record(
        kind="live_meter_window",
        payload={"reads": 12},
        source="watch",
        ttl_seconds=5,
        invalidates_on=("playback_stop",),
    )

    assert store.invalidate(event="project_structure_change", reason="test") == 1
    assert store.get(static.observation_id).freshness_status(clock()) == "stale"
    assert store.get(live.observation_id).freshness_status(clock()) == "fresh"


def test_observation_store_marks_partial_and_unavailable() -> None:
    clock = FakeClock()
    store = ObservationStore(clock=clock)

    partial = store.record(
        kind="routing_snapshot",
        payload={"routes": []},
        source="broker",
        ttl_seconds=60,
        errors=("plugin list timed out",),
    )
    unavailable = store.record(
        kind="live_meter_window",
        payload={},
        source="watch",
        ttl_seconds=5,
        errors=("bridge unavailable",),
    )

    assert partial.freshness_status(clock()) == "partial"
    assert unavailable.freshness_status(clock()) == "unavailable"
    assert store.latest("routing_snapshot").observation_id == partial.observation_id
    assert store.latest("live_meter_window") is None
    assert store.latest("live_meter_window", include_stale=True) == unavailable


def test_observation_store_prunes_oldest_entries_per_kind() -> None:
    clock = FakeClock()
    store = ObservationStore(clock=clock, max_entries_per_kind=2)

    first = store.record(kind="snapshot", payload=1, source="test", ttl_seconds=60)
    clock.advance(1)
    second = store.record(kind="snapshot", payload=2, source="test", ttl_seconds=60)
    clock.advance(1)
    third = store.record(kind="snapshot", payload=3, source="test", ttl_seconds=60)

    rows = store.list(kind="snapshot")

    assert store.get(first.observation_id) is None
    assert [row.observation_id for row in rows] == [
        second.observation_id,
        third.observation_id,
    ]


def test_observation_store_purges_stale_entries() -> None:
    clock = FakeClock()
    store = ObservationStore(clock=clock)
    store.record(kind="short", payload={"ok": True}, source="test", ttl_seconds=1)
    store.record(kind="long", payload={"ok": True}, source="test", ttl_seconds=10)

    clock.advance(2)

    assert store.purge_stale() == 1
    assert store.latest("short", include_stale=True) is None
    assert store.latest("long") is not None

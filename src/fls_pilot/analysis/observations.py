"""In-memory observation store with freshness and invalidation policy."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from time import time
from typing import Any
from uuid import uuid4


def _observation_id(kind: str) -> str:
    safe_kind = str(kind or "observation").strip().lower().replace(" ", "_")
    return f"obs_{safe_kind}_{uuid4().hex[:12]}"


@dataclass(frozen=True)
class Observation:
    observation_id: str
    kind: str
    payload: Any
    source: str
    created_at: float
    ttl_seconds: float | None
    confidence: str = "unknown"
    project_fingerprint: str | None = None
    invalidates_on: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()
    metadata: dict[str, Any] | None = None
    invalidated_at: float | None = None
    invalidation_reason: str | None = None

    @property
    def valid_until(self) -> float | None:
        if self.ttl_seconds is None:
            return None
        return self.created_at + float(self.ttl_seconds)

    def freshness_status(self, now: float | None = None) -> str:
        current = time() if now is None else float(now)
        if self.invalidated_at is not None:
            return "stale"
        if self.valid_until is not None and current > self.valid_until:
            return "stale"
        if self.errors and self.payload in ({}, [], None, ""):
            return "unavailable"
        if self.errors:
            return "partial"
        return "fresh"

    def is_fresh(self, now: float | None = None) -> bool:
        return self.freshness_status(now) == "fresh"

    def is_usable(self, now: float | None = None) -> bool:
        return self.freshness_status(now) in {"fresh", "partial"}

    def to_dict(self, now: float | None = None) -> dict[str, Any]:
        out: dict[str, Any] = {
            "observation_id": self.observation_id,
            "kind": self.kind,
            "source": self.source,
            "created_at": self.created_at,
            "ttl_seconds": self.ttl_seconds,
            "freshness": self.freshness_status(now),
            "confidence": self.confidence,
            "payload": self.payload,
            "invalidates_on": list(self.invalidates_on),
            "errors": list(self.errors),
        }
        if self.valid_until is not None:
            out["valid_until"] = self.valid_until
        if self.project_fingerprint:
            out["project_fingerprint"] = self.project_fingerprint
        if self.metadata:
            out["metadata"] = dict(self.metadata)
        if self.invalidated_at is not None:
            out["invalidated_at"] = self.invalidated_at
        if self.invalidation_reason:
            out["invalidation_reason"] = self.invalidation_reason
        return out


class ObservationStore:
    """Bounded in-memory store for reusable read-only workflow observations."""

    def __init__(
        self,
        *,
        clock: Callable[[], float] | None = None,
        max_entries_per_kind: int = 20,
    ) -> None:
        self._clock = clock or time
        self._max_entries_per_kind = max(1, int(max_entries_per_kind))
        self._observations: dict[str, Observation] = {}
        self._by_kind: dict[str, list[str]] = {}

    def record(
        self,
        *,
        kind: str,
        payload: Any,
        source: str,
        ttl_seconds: float | None,
        confidence: str = "unknown",
        project_fingerprint: str | None = None,
        invalidates_on: list[str] | tuple[str, ...] | None = None,
        observation_id: str | None = None,
        errors: list[str] | tuple[str, ...] | None = None,
        metadata: dict[str, Any] | None = None,
        created_at: float | None = None,
    ) -> Observation:
        kind = str(kind)
        observation = Observation(
            observation_id=observation_id or _observation_id(kind),
            kind=kind,
            payload=payload,
            source=str(source),
            created_at=self._clock() if created_at is None else float(created_at),
            ttl_seconds=ttl_seconds,
            confidence=str(confidence),
            project_fingerprint=project_fingerprint,
            invalidates_on=tuple(str(item) for item in (invalidates_on or ())),
            errors=tuple(str(item) for item in (errors or ())),
            metadata=dict(metadata or {}),
        )
        self._observations[observation.observation_id] = observation
        self._by_kind.setdefault(kind, []).append(observation.observation_id)
        self._prune_kind(kind)
        return observation

    def get(self, observation_id: str) -> Observation | None:
        return self._observations.get(str(observation_id))

    def latest(
        self,
        kind: str,
        *,
        include_stale: bool = False,
        project_fingerprint: str | None = None,
    ) -> Observation | None:
        rows = self.list(
            kind=kind,
            include_stale=include_stale,
            project_fingerprint=project_fingerprint,
        )
        if not rows:
            return None
        return max(rows, key=lambda row: row.created_at)

    def list(
        self,
        *,
        kind: str | None = None,
        include_stale: bool = True,
        project_fingerprint: str | None = None,
    ) -> list[Observation]:
        ids = self._by_kind.get(str(kind), []) if kind is not None else list(self._observations)
        rows = []
        now = self._clock()
        for observation_id in ids:
            row = self._observations.get(observation_id)
            if row is None:
                continue
            if project_fingerprint is not None and row.project_fingerprint != project_fingerprint:
                continue
            if not include_stale and not row.is_usable(now):
                continue
            rows.append(row)
        return sorted(rows, key=lambda row: row.created_at)

    def invalidate(
        self,
        *,
        kind: str | None = None,
        observation_id: str | None = None,
        event: str | None = None,
        reason: str = "manual invalidation",
    ) -> int:
        targets = self._matching_ids(kind=kind, observation_id=observation_id, event=event)
        invalidated = 0
        now = self._clock()
        for target_id in targets:
            row = self._observations.get(target_id)
            if row is None or row.invalidated_at is not None:
                continue
            self._observations[target_id] = replace(
                row,
                invalidated_at=now,
                invalidation_reason=reason,
            )
            invalidated += 1
        return invalidated

    def purge_stale(self) -> int:
        now = self._clock()
        stale_ids = [
            observation_id
            for observation_id, row in self._observations.items()
            if row.freshness_status(now) == "stale"
        ]
        for observation_id in stale_ids:
            self._remove(observation_id)
        return len(stale_ids)

    def clear(self) -> None:
        self._observations.clear()
        self._by_kind.clear()

    def now(self) -> float:
        return self._clock()

    def _matching_ids(
        self,
        *,
        kind: str | None,
        observation_id: str | None,
        event: str | None,
    ) -> list[str]:
        if observation_id is not None:
            return [str(observation_id)]
        candidate_ids = (
            list(self._by_kind.get(str(kind), [])) if kind is not None else list(self._observations)
        )
        if event is None:
            return candidate_ids
        matches = []
        for row_id in candidate_ids:
            row = self._observations.get(row_id)
            if row is not None and event in row.invalidates_on:
                matches.append(row_id)
        return matches

    def _prune_kind(self, kind: str) -> None:
        ids = self._by_kind.get(kind, [])
        if len(ids) <= self._max_entries_per_kind:
            return
        excess = ids[: len(ids) - self._max_entries_per_kind]
        for observation_id in excess:
            self._remove(observation_id)

    def _remove(self, observation_id: str) -> None:
        row = self._observations.pop(observation_id, None)
        if row is None:
            return
        ids = self._by_kind.get(row.kind, [])
        self._by_kind[row.kind] = [row_id for row_id in ids if row_id != observation_id]

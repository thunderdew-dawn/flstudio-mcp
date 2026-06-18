"""Runtime-owned project identity and snapshot revision tracking."""

from __future__ import annotations

import hashlib
from dataclasses import replace
from pathlib import Path
from typing import Any

from ..analysis.broker import StaticProjectSnapshot
from .contracts import ProjectContext, RuntimeSession, utc_now_iso


class ProjectContextService:
    def __init__(self, session: RuntimeSession) -> None:
        self._session = session
        self._context = ProjectContext.unknown(session.id)

    @property
    def current(self) -> ProjectContext:
        return self._context

    def update(self, snapshot: StaticProjectSnapshot) -> ProjectContext:
        identity_hint, confidence = _identity_hint(snapshot.project_state)
        scope_id = _scope_id(
            runtime_session_id=self._session.id,
            identity_hint=identity_hint,
        )
        previous = self._context
        same_scope = previous.project_scope_id == scope_id and scope_id != "unknown"
        if same_scope and previous.snapshot_id == snapshot.snapshot_id:
            revision = previous.snapshot_revision
            created_at = previous.created_at
        else:
            revision = previous.snapshot_revision + 1 if same_scope else 1
            created_at = previous.created_at if same_scope else utc_now_iso()
        self._context = ProjectContext(
            runtime_session_id=self._session.id,
            project_scope_id=scope_id,
            project_identity_hint=identity_hint,
            project_identity_confidence=confidence,
            project_fingerprint=snapshot.project_fingerprint,
            snapshot_id=snapshot.snapshot_id,
            snapshot_revision=revision,
            created_at=created_at,
            refreshed_at=utc_now_iso(),
            source_observation_ids=snapshot.source_observation_ids,
            freshness=snapshot.coverage.status,
        )
        return self._context

    def invalidate(self, reason: str) -> ProjectContext:
        self._context = replace(
            self._context,
            freshness="stale",
            refreshed_at=utc_now_iso(),
            invalidation_reasons=(
                *self._context.invalidation_reasons,
                str(reason),
            ),
        )
        return self._context


def _identity_hint(project_state: dict[str, Any]) -> tuple[str | None, str]:
    raw_path = str(project_state.get("path") or "").strip()
    if raw_path:
        return str(Path(raw_path).expanduser()), "high"
    title = str(
        project_state.get("title")
        or project_state.get("project_title")
        or project_state.get("name")
        or ""
    ).strip()
    if title:
        return f"title:{title}", "medium"
    return None, "unknown"


def _scope_id(*, runtime_session_id: str, identity_hint: str | None) -> str:
    if not identity_hint:
        return "unknown"
    encoded = f"{runtime_session_id}\0{identity_hint}".encode("utf-8")
    return f"project_{hashlib.sha256(encoded).hexdigest()[:16]}"

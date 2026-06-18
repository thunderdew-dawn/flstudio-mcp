"""Project-scoped links between immutable audio artifacts and Runtime evidence."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

EVIDENCE_LINK_CONTRACT_VERSION = "fls-pilot.evidence-link.v1"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class EvidenceLink:
    link_id: str
    artifact_id: str
    runtime_session_id: str
    project_scope_id: str
    project_fingerprint: str
    evidence_kind: str
    stem_role: str | None
    workflow_targets: tuple[str, ...]
    created_at: str
    confirmed_by_user: bool
    invalidated_at: str | None = None
    invalidation_reason: str | None = None

    @property
    def active(self) -> bool:
        return self.invalidated_at is None

    def compatible_with(self, context: Any) -> bool:
        if not self.active or self.runtime_session_id != context.runtime_session_id:
            return False
        if context.is_known:
            return (
                self.project_scope_id == context.project_scope_id
                and self.project_fingerprint == context.project_fingerprint
            )
        return self.confirmed_by_user and self.project_scope_id == "unknown"

    def to_dict(self) -> dict[str, Any]:
        return {
            "contract_version": EVIDENCE_LINK_CONTRACT_VERSION,
            "link_id": self.link_id,
            "artifact_id": self.artifact_id,
            "runtime_session_id": self.runtime_session_id,
            "project_scope_id": self.project_scope_id,
            "project_fingerprint": self.project_fingerprint,
            "evidence_kind": self.evidence_kind,
            "stem_role": self.stem_role,
            "workflow_targets": list(self.workflow_targets),
            "created_at": self.created_at,
            "confirmed_by_user": self.confirmed_by_user,
            "active": self.active,
            "invalidated_at": self.invalidated_at,
            "invalidation_reason": self.invalidation_reason,
        }


class EvidenceLinkStore:
    def __init__(self) -> None:
        self._links: dict[str, EvidenceLink] = {}

    def create(
        self,
        *,
        artifact_id: str,
        context: Any,
        evidence_kind: str,
        stem_role: str | None,
        workflow_targets: tuple[str, ...],
        confirmed_by_user: bool,
    ) -> EvidenceLink:
        if not context.is_known and not confirmed_by_user:
            raise ValueError(
                "user_confirmation_required: current project association is unknown"
            )
        normalized_targets = tuple(
            sorted({str(row) for row in workflow_targets if str(row).strip()})
        )
        for link_id, link in tuple(self._links.items()):
            same_slot = (
                link.runtime_session_id == context.runtime_session_id
                and link.project_scope_id == context.project_scope_id
                and link.evidence_kind == evidence_kind
                and link.stem_role == stem_role
                and set(link.workflow_targets) == set(normalized_targets)
            )
            if same_slot and link.artifact_id != artifact_id and link.active:
                self._links[link_id] = replace(
                    link,
                    invalidated_at=_utc_now_iso(),
                    invalidation_reason="audio_source_hash_changed",
                )
        link = EvidenceLink(
            link_id=f"evidence_{uuid4().hex[:16]}",
            artifact_id=str(artifact_id),
            runtime_session_id=context.runtime_session_id,
            project_scope_id=context.project_scope_id,
            project_fingerprint=context.project_fingerprint,
            evidence_kind=str(evidence_kind),
            stem_role=str(stem_role) if stem_role else None,
            workflow_targets=normalized_targets,
            created_at=_utc_now_iso(),
            confirmed_by_user=bool(confirmed_by_user),
        )
        self._links[link.link_id] = link
        return link

    def get(self, link_id: str) -> EvidenceLink | None:
        return self._links.get(str(link_id))

    def list(
        self,
        *,
        context: Any | None = None,
        workflow_target: str | None = None,
        include_inactive: bool = False,
    ) -> tuple[EvidenceLink, ...]:
        rows = []
        for link in self._links.values():
            if not include_inactive and not link.active:
                continue
            if context is not None and not link.compatible_with(context):
                continue
            if (
                workflow_target
                and link.workflow_targets
                and workflow_target not in link.workflow_targets
            ):
                continue
            rows.append(link)
        return tuple(sorted(rows, key=lambda row: row.created_at))

    def invalidate(self, link_id: str, reason: str) -> EvidenceLink:
        link = self._links[str(link_id)]
        invalidated = replace(
            link,
            invalidated_at=_utc_now_iso(),
            invalidation_reason=str(reason),
        )
        self._links[link.link_id] = invalidated
        return invalidated

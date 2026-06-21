"""SQLite-backed workflow definition store.

The store keeps an immutable-ish version history for admin-defined custom
workflows and a read-only mirror of built-in workflow declarations. Built-ins
are mirrored so admin surfaces can expose one consistent WorkflowDefinition
shape without allowing built-in rows to be edited or archived.
"""

from __future__ import annotations

import contextlib
import json
import sqlite3
from collections.abc import Iterable, Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..workflow_identity import is_builtin_workflow_id, is_custom_workflow_id
from ..workflows.registry import WorkflowDeclaration, WorkflowRegistry
from .workflow_models import WorkflowDefinition

DEFAULT_WORKFLOW_STORE = Path.home() / ".fls-pilot" / "runtime" / "workflows.sqlite3"

_FORBIDDEN_ADMIN_KEYS = frozenset({"code", "script", "cmd", "command", "raw"})
_JSON_FIELDS = frozenset(
    {
        "description",
        "analysis_report_required",
        "health_inclusion_policy",
        "requirements",
        "parent_workflow_id",
        "panel_id",
        "group",
        "endpoint",
        "action_label",
        "safety_note",
        "supported_next_actions",
        "manual_only_actions",
        "forbidden_actions",
        "inputs_schema",
        "metadata",
        "capabilities",
        "pack_id",
        "pack_version",
        "edition",
        "license_required",
    }
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _loads_json(value: str | None) -> dict[str, Any]:
    if not value:
        return {}
    data = json.loads(value)
    return data if isinstance(data, dict) else {}


def _dumps_json(value: Mapping[str, Any]) -> str:
    return json.dumps(dict(value), sort_keys=True, separators=(",", ":"))


def validate_admin_payload(payload: Mapping[str, Any]) -> None:
    """Reject dangerous executable-ish admin payload fields recursively."""
    if not isinstance(payload, Mapping):
        raise ValueError("workflow definition must be an object")

    def visit(value: Any) -> None:
        if isinstance(value, Mapping):
            for key, child in value.items():
                key_text = str(key)
                if key_text.lower() in _FORBIDDEN_ADMIN_KEYS:
                    raise ValueError(f"Dangerous field rejected: {key_text}")
                visit(child)
        elif isinstance(value, list | tuple):
            for child in value:
                visit(child)

    visit(payload)


class WorkflowStore:
    """SQLite store for built-in mirrors and custom workflow definitions."""

    def __init__(self, db_path: str | Path | None = None) -> None:
        self._db_path = str(Path(db_path or DEFAULT_WORKFLOW_STORE).expanduser())
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self) -> None:
        with contextlib.closing(sqlite3.connect(self._db_path)) as conn:
            with conn:
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS workflow_definitions (
                      workflow_id TEXT NOT NULL,
                      version INTEGER NOT NULL,
                      title TEXT NOT NULL,
                      kind TEXT NOT NULL,
                      status TEXT NOT NULL,
                      origin TEXT NOT NULL,
                      protected INTEGER NOT NULL,
                      runner_type TEXT NOT NULL,
                      runner_ref TEXT,
                      payload_json TEXT NOT NULL,
                      created_at TEXT NOT NULL,
                      updated_at TEXT NOT NULL,
                      archived_at TEXT,
                      PRIMARY KEY (workflow_id, version)
                    )
                    """
                )
                conn.execute(
                    """
                    CREATE INDEX IF NOT EXISTS workflow_definitions_latest_idx
                    ON workflow_definitions(workflow_id, version DESC)
                    """
                )
                conn.execute(
                    """
                    CREATE INDEX IF NOT EXISTS workflow_definitions_origin_status_idx
                    ON workflow_definitions(origin, status, archived_at)
                    """
                )

    def mirror_builtins(self, registry: WorkflowRegistry) -> dict[str, int]:
        """Mirror built-in declarations as protected version-1 definitions."""
        versions: dict[str, int] = {}
        for declaration in registry.list(include_inactive=True):
            model = self._definition_from_declaration(declaration)
            self._upsert_builtin(model)
            versions[model.workflow_id] = model.version
        return versions

    def list_definitions(self, *, include_archived: bool = False) -> tuple[WorkflowDefinition, ...]:
        """List latest definitions for each workflow id."""
        query = """
            SELECT
                d.workflow_id, d.version, d.title, d.kind, d.status, d.origin,
                d.protected, d.runner_type, d.runner_ref, d.payload_json,
                d.created_at, d.updated_at, d.archived_at
            FROM workflow_definitions d
            JOIN (
                SELECT workflow_id, MAX(version) AS version
                FROM workflow_definitions
                GROUP BY workflow_id
            ) latest
              ON latest.workflow_id = d.workflow_id AND latest.version = d.version
        """
        if not include_archived:
            query += " WHERE d.status != 'archived' AND d.archived_at IS NULL"
        query += " ORDER BY d.origin, d.workflow_id"

        with contextlib.closing(sqlite3.connect(self._db_path)) as conn:
            cursor = conn.execute(query)
            return tuple(self._row_to_model(row) for row in cursor.fetchall())

    def get_definition(self, workflow_id: str, version: int | None = None) -> WorkflowDefinition:
        """Get one definition by workflow id and optional version."""
        params: tuple[Any, ...]
        if version is None:
            query = """
                SELECT
                    workflow_id, version, title, kind, status, origin,
                    protected, runner_type, runner_ref, payload_json,
                    created_at, updated_at, archived_at
                FROM workflow_definitions
                WHERE workflow_id = ?
                ORDER BY version DESC
                LIMIT 1
            """
            params = (workflow_id,)
        else:
            query = """
                SELECT
                    workflow_id, version, title, kind, status, origin,
                    protected, runner_type, runner_ref, payload_json,
                    created_at, updated_at, archived_at
                FROM workflow_definitions
                WHERE workflow_id = ? AND version = ?
            """
            params = (workflow_id, int(version))

        with contextlib.closing(sqlite3.connect(self._db_path)) as conn:
            row = conn.execute(query, params).fetchone()
            if row is None:
                raise KeyError(f"Workflow definition not found: {workflow_id}")
            return self._row_to_model(row)

    def create_custom(
        self,
        definition: Mapping[str, Any],
        *,
        valid_job_kinds: Iterable[str] = (),
    ) -> WorkflowDefinition:
        """Create a new custom workflow definition at version 1."""
        validate_admin_payload(definition)
        workflow_id = str(definition.get("workflow_id") or "").strip()
        if is_builtin_workflow_id(workflow_id):
            raise ValueError(f"Cannot overwrite built-in workflow: {workflow_id}")
        if not is_custom_workflow_id(workflow_id):
            raise ValueError(f"Invalid custom workflow ID: {workflow_id}")

        try:
            existing = self.get_definition(workflow_id)
        except KeyError:
            existing = None
        if existing is not None and existing.archived_at is None and existing.status != "archived":
            raise ValueError(f"Custom workflow already exists: {workflow_id}")

        now = _utc_now()
        model = self._model_from_payload(
            definition,
            workflow_id=workflow_id,
            version=1,
            origin="custom",
            protected=False,
            created_at=now,
            updated_at=now,
            archived_at=None,
            valid_job_kinds=tuple(valid_job_kinds),
        )
        self._insert_definition(model)
        return self.get_definition(workflow_id)

    def update_custom(
        self,
        workflow_id: str,
        patch: Mapping[str, Any],
        *,
        valid_job_kinds: Iterable[str] = (),
    ) -> WorkflowDefinition:
        """Create a new version of an existing custom workflow definition."""
        if is_builtin_workflow_id(workflow_id):
            raise ValueError("Built-in workflows cannot be updated")
        if not is_custom_workflow_id(workflow_id):
            raise ValueError(f"Invalid custom workflow ID: {workflow_id}")
        validate_admin_payload(patch)

        current = self.get_definition(workflow_id)
        if current.origin != "custom" or current.protected:
            raise ValueError("Built-in workflows cannot be updated")
        if current.archived_at is not None or current.status == "archived":
            raise ValueError(f"Archived workflows cannot be updated: {workflow_id}")

        merged = current.to_dict()
        merged.update(dict(patch))
        merged["workflow_id"] = workflow_id
        merged.pop("id", None)

        model = self._model_from_payload(
            merged,
            workflow_id=workflow_id,
            version=current.version + 1,
            origin="custom",
            protected=False,
            created_at=current.created_at,
            updated_at=_utc_now(),
            archived_at=current.archived_at,
            valid_job_kinds=tuple(valid_job_kinds),
        )
        self._insert_definition(model)
        return self.get_definition(workflow_id)

    def archive_custom(self, workflow_id: str) -> WorkflowDefinition:
        """Archive a custom workflow by writing a new archived version."""
        if is_builtin_workflow_id(workflow_id):
            raise ValueError("Built-in workflows cannot be archived")
        if not is_custom_workflow_id(workflow_id):
            raise ValueError(f"Invalid custom workflow ID: {workflow_id}")

        current = self.get_definition(workflow_id)
        if current.origin != "custom" or current.protected:
            raise ValueError("Built-in workflows cannot be archived")

        archived_at = _utc_now()
        data = current.to_dict()
        data["status"] = "archived"
        model = self._model_from_payload(
            data,
            workflow_id=workflow_id,
            version=current.version + 1,
            origin="custom",
            protected=False,
            created_at=current.created_at,
            updated_at=archived_at,
            archived_at=archived_at,
            valid_job_kinds=(),
            validate_job_kind=False,
        )
        self._insert_definition(model)
        return self.get_definition(workflow_id)

    def _definition_from_declaration(self, declaration: WorkflowDeclaration) -> WorkflowDefinition:
        requirements = declaration.requirements.to_dict() if declaration.requirements else None
        now = "1970-01-01T00:00:00+00:00"
        return WorkflowDefinition(
            workflow_id=declaration.id,
            version=1,
            title=declaration.title,
            description=str(declaration.metadata.get("description") or ""),
            kind=declaration.kind,
            status=declaration.status,
            origin="builtin",
            protected=True,
            runner_type="builtin",
            runner_ref=declaration.id,
            analysis_report_required=declaration.analysis_report_required,
            health_inclusion_policy=declaration.health_inclusion_policy,
            requirements=requirements,
            parent_workflow_id=declaration.parent_workflow_id,
            panel_id=declaration.panel_id,
            group=declaration.group,
            endpoint=declaration.endpoint,
            action_label=declaration.action_label,
            safety_note=declaration.safety_note,
            supported_next_actions=declaration.supported_next_actions,
            manual_only_actions=declaration.manual_only_actions,
            forbidden_actions=declaration.forbidden_actions,
            inputs_schema={},
            metadata=dict(declaration.metadata),
            capabilities=(),
            created_at=now,
            updated_at=now,
            archived_at=None,
        )

    def _upsert_builtin(self, model: WorkflowDefinition) -> None:
        with contextlib.closing(sqlite3.connect(self._db_path)) as conn:
            with conn:
                conn.execute(
                    """
                    INSERT INTO workflow_definitions (
                        workflow_id, version, title, kind, status, origin,
                        protected, runner_type, runner_ref, payload_json,
                        created_at, updated_at, archived_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(workflow_id, version) DO UPDATE SET
                        title = excluded.title,
                        kind = excluded.kind,
                        status = excluded.status,
                        origin = excluded.origin,
                        protected = excluded.protected,
                        runner_type = excluded.runner_type,
                        runner_ref = excluded.runner_ref,
                        payload_json = excluded.payload_json,
                        updated_at = excluded.updated_at,
                        archived_at = excluded.archived_at
                    """,
                    self._db_tuple(model),
                )

    def _insert_definition(self, model: WorkflowDefinition) -> None:
        with contextlib.closing(sqlite3.connect(self._db_path)) as conn:
            with conn:
                conn.execute(
                    """
                    INSERT INTO workflow_definitions (
                        workflow_id, version, title, kind, status, origin,
                        protected, runner_type, runner_ref, payload_json,
                        created_at, updated_at, archived_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    self._db_tuple(model),
                )

    def _db_tuple(self, model: WorkflowDefinition) -> tuple[Any, ...]:
        payload = {
            "description": model.description,
            "analysis_report_required": model.analysis_report_required,
            "health_inclusion_policy": model.health_inclusion_policy,
            "requirements": model.requirements,
            "parent_workflow_id": model.parent_workflow_id,
            "panel_id": model.panel_id,
            "group": model.group,
            "endpoint": model.endpoint,
            "action_label": model.action_label,
            "safety_note": model.safety_note,
            "supported_next_actions": list(model.supported_next_actions),
            "manual_only_actions": list(model.manual_only_actions),
            "forbidden_actions": list(model.forbidden_actions),
            "inputs_schema": model.inputs_schema,
            "metadata": model.metadata,
            "capabilities": list(model.capabilities),
            "pack_id": model.pack_id,
            "pack_version": model.pack_version,
            "edition": model.edition,
            "license_required": model.license_required,
        }
        return (
            model.workflow_id,
            model.version,
            model.title,
            model.kind,
            model.status,
            model.origin,
            1 if model.protected else 0,
            model.runner_type,
            model.runner_ref,
            _dumps_json(payload),
            model.created_at,
            model.updated_at,
            model.archived_at,
        )

    def _model_from_payload(
        self,
        payload: Mapping[str, Any],
        *,
        workflow_id: str,
        version: int,
        origin: str,
        protected: bool,
        created_at: str,
        updated_at: str,
        archived_at: str | None,
        valid_job_kinds: Iterable[str],
        validate_job_kind: bool = True,
    ) -> WorkflowDefinition:
        runner_type = str(payload.get("runner_type") or "job").strip()
        if runner_type not in {"builtin", "job"}:
            raise ValueError(f"Invalid runner_type: {runner_type}")
        runner_ref_value = payload.get("runner_ref")
        runner_ref = str(runner_ref_value).strip() if runner_ref_value is not None else None
        if runner_ref == "":
            runner_ref = None

        status = str(payload.get("status") or "active").strip() or "active"
        title = str(payload.get("title") or workflow_id).strip() or workflow_id
        kind = str(payload.get("kind") or "analysis_workflow").strip() or "analysis_workflow"

        if runner_type == "job":
            valid_jobs = set(valid_job_kinds)
            is_runnable_status = status == "active"
            if is_runnable_status and not runner_ref:
                raise ValueError("runner_type 'job' requires a runner_ref when status is active")
            if validate_job_kind and runner_ref and valid_jobs and runner_ref not in valid_jobs:
                raise ValueError(f"runner_ref {runner_ref!r} is not a registered job kind")
            if validate_job_kind and is_runnable_status and runner_ref and not valid_jobs:
                raise ValueError(f"runner_ref {runner_ref!r} is not a registered job kind")
            if validate_job_kind and is_runnable_status and runner_ref and runner_ref not in valid_jobs:
                raise ValueError(f"runner_ref {runner_ref!r} is not a registered job kind")

        return WorkflowDefinition(
            workflow_id=workflow_id,
            version=version,
            title=title,
            description=str(payload.get("description") or ""),
            kind=kind,
            status=status,  # type: ignore[arg-type]
            origin=origin,  # type: ignore[arg-type]
            protected=protected,
            runner_type=runner_type,  # type: ignore[arg-type]
            runner_ref=runner_ref,
            analysis_report_required=bool(payload.get("analysis_report_required", False)),
            health_inclusion_policy=str(
                payload.get("health_inclusion_policy") or "optional_context_report"
            ),
            requirements=(
                dict(payload.get("requirements"))
                if isinstance(payload.get("requirements"), Mapping)
                else None
            ),
            parent_workflow_id=(
                str(payload.get("parent_workflow_id"))
                if payload.get("parent_workflow_id") is not None
                else None
            ),
            panel_id=str(payload.get("panel_id")) if payload.get("panel_id") is not None else None,
            group=str(payload.get("group") or ""),
            endpoint=str(payload.get("endpoint")) if payload.get("endpoint") is not None else None,
            action_label=(
                str(payload.get("action_label"))
                if payload.get("action_label") is not None
                else None
            ),
            safety_note=str(payload.get("safety_note") or ""),
            supported_next_actions=tuple(payload.get("supported_next_actions") or ()),
            manual_only_actions=tuple(payload.get("manual_only_actions") or ()),
            forbidden_actions=tuple(payload.get("forbidden_actions") or ()),
            inputs_schema=(
                dict(payload.get("inputs_schema"))
                if isinstance(payload.get("inputs_schema"), Mapping)
                else {}
            ),
            metadata=(
                dict(payload.get("metadata"))
                if isinstance(payload.get("metadata"), Mapping)
                else {}
            ),
            capabilities=tuple(payload.get("capabilities") or ()),
            pack_id=str(payload.get("pack_id")) if payload.get("pack_id") is not None else None,
            pack_version=(
                str(payload.get("pack_version"))
                if payload.get("pack_version") is not None
                else None
            ),
            edition=str(payload.get("edition")) if payload.get("edition") is not None else None,
            license_required=(
                str(payload.get("license_required"))
                if payload.get("license_required") is not None
                else None
            ),
            created_at=created_at,
            updated_at=updated_at,
            archived_at=archived_at,
        )

    def _row_to_model(self, row: Any) -> WorkflowDefinition:
        payload = _loads_json(row[9])
        data: dict[str, Any] = {field: payload.get(field) for field in _JSON_FIELDS}
        return WorkflowDefinition(
            workflow_id=row[0],
            version=int(row[1]),
            title=row[2],
            kind=row[3],
            status=row[4],
            origin=row[5],
            protected=bool(row[6]),
            runner_type=row[7],
            runner_ref=row[8],
            description=str(data.get("description") or ""),
            analysis_report_required=bool(data.get("analysis_report_required", False)),
            health_inclusion_policy=str(
                data.get("health_inclusion_policy") or "optional_context_report"
            ),
            requirements=(
                dict(data.get("requirements"))
                if isinstance(data.get("requirements"), Mapping)
                else None
            ),
            parent_workflow_id=(
                str(data.get("parent_workflow_id"))
                if data.get("parent_workflow_id") is not None
                else None
            ),
            panel_id=str(data.get("panel_id")) if data.get("panel_id") is not None else None,
            group=str(data.get("group") or ""),
            endpoint=str(data.get("endpoint")) if data.get("endpoint") is not None else None,
            action_label=(
                str(data.get("action_label")) if data.get("action_label") is not None else None
            ),
            safety_note=str(data.get("safety_note") or ""),
            supported_next_actions=tuple(data.get("supported_next_actions") or ()),
            manual_only_actions=tuple(data.get("manual_only_actions") or ()),
            forbidden_actions=tuple(data.get("forbidden_actions") or ()),
            inputs_schema=(
                dict(data.get("inputs_schema"))
                if isinstance(data.get("inputs_schema"), Mapping)
                else {}
            ),
            metadata=(
                dict(data.get("metadata"))
                if isinstance(data.get("metadata"), Mapping)
                else {}
            ),
            capabilities=tuple(data.get("capabilities") or ()),
            pack_id=str(data.get("pack_id")) if data.get("pack_id") is not None else None,
            pack_version=(
                str(data.get("pack_version")) if data.get("pack_version") is not None else None
            ),
            edition=str(data.get("edition")) if data.get("edition") is not None else None,
            license_required=(
                str(data.get("license_required"))
                if data.get("license_required") is not None
                else None
            ),
            created_at=row[10],
            updated_at=row[11],
            archived_at=row[12],
        )

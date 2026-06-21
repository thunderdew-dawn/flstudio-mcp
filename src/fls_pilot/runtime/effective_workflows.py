from __future__ import annotations

import logging
from typing import Any

from ..workflow_identity import is_custom_workflow_id, normalize_workflow_id
from ..workflows.registry import WorkflowDeclaration, WorkflowRegistry
from .workflow_models import WorkflowDefinition
from .workflow_store import WorkflowStore

logger = logging.getLogger(__name__)


class EffectiveWorkflowRegistry:
    """A composed view of built-in workflow declarations and custom definitions."""

    def __init__(self, base_registry: WorkflowRegistry, store: WorkflowStore) -> None:
        self._base_registry = base_registry
        self._store = store

    def list_effective(self, include_archived: bool = False) -> tuple[Any, ...]:
        """List all effective workflows in built-in registry order plus customs."""
        try:
            stored_all = self._store.list_definitions(include_archived=True)
        except Exception as exc:
            logger.warning("Could not load workflow definitions from store: %s", exc)
            stored_all = ()

        stored_by_id = {row.workflow_id: row for row in stored_all if row.origin == "builtin"}
        effective: list[Any] = []
        builtin_ids: set[str] = set()

        for declaration in self._base_registry.list(include_inactive=True):
            builtin_ids.add(declaration.id)
            effective.append(stored_by_id.get(declaration.id) or declaration)

        for model in stored_all:
            if model.origin != "custom":
                continue

            if not include_archived and (model.status != "active" or model.archived_at is not None):
                continue

            if not is_custom_workflow_id(model.workflow_id):
                logger.warning("Ignoring custom workflow with invalid ID: %r", model.workflow_id)
                continue

            if model.workflow_id in builtin_ids:
                logger.warning(
                    "Ignoring custom workflow attempting to override built-in ID: %r",
                    model.workflow_id,
                )
                continue

            effective.append(model)

        return tuple(effective)

    def get_effective(self, workflow_id: str) -> Any:
        """Get a specific workflow by ID, searching built-ins then custom."""
        try:
            normalized = normalize_workflow_id(workflow_id, allow_custom=True)
        except ValueError as exc:
            raise KeyError(str(exc)) from exc

        if not is_custom_workflow_id(normalized):
            try:
                model = self._store.get_definition(normalized)
                if model.origin == "builtin" and model.protected:
                    return model
            except KeyError:
                pass
            try:
                return self._base_registry.get(normalized)
            except (KeyError, ValueError) as exc:
                raise KeyError(f"Workflow not found: {normalized}") from exc

        try:
            model = self._store.get_definition(normalized)
        except KeyError as exc:
            raise KeyError(f"Workflow not found: {normalized}") from exc

        if model.origin != "custom" or model.status != "active" or model.archived_at is not None:
            raise KeyError(f"Workflow not found or not active: {normalized}")

        return model

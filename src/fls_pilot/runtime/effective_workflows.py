from __future__ import annotations

import logging
from typing import Any

from .workflow_models import WorkflowDefinition
from .workflow_store import WorkflowStore
from ..workflows.registry import WorkflowRegistry
from ..workflow_identity import is_custom_workflow_id, normalize_workflow_id

logger = logging.getLogger(__name__)


class EffectiveWorkflowRegistry:
    """A composed view of built-in workflow declarations and custom workflow definitions."""

    def __init__(self, base_registry: WorkflowRegistry, store: WorkflowStore) -> None:
        self._base_registry = base_registry
        self._store = store

    def list_effective(self, include_archived: bool = False) -> tuple[Any, ...]:
        """List all effective workflows (built-ins + active custom).
        
        Returns a mix of WorkflowDeclaration (for built-ins) and 
        WorkflowDefinition (for custom).
        """
        # 1. Base Built-ins
        effective: list[Any] = list(self._base_registry.list(include_inactive=True))
        builtin_ids = {row.id for row in effective}

        # 2. Custom definitions from store
        try:
            stored = self._store.list_definitions(include_archived=include_archived)
        except Exception as exc:
            logger.warning(f"Could not load custom workflows from store: {exc}")
            stored = ()

        for model in stored:
            if model.origin != "custom":
                continue
                
            if not include_archived and model.status != "active":
                continue
                
            if not is_custom_workflow_id(model.workflow_id):
                logger.warning(f"Ignoring custom workflow with invalid ID: {model.workflow_id!r}")
                continue
                
            if model.workflow_id in builtin_ids:
                logger.warning(f"Ignoring custom workflow attempting to override built-in ID: {model.workflow_id!r}")
                continue
                
            effective.append(model)
            
        return tuple(effective)

    def get_effective(self, workflow_id: str) -> Any:
        """Get a specific workflow by ID, searching built-ins then custom."""
        try:
            normalized = normalize_workflow_id(workflow_id, allow_custom=True)
        except ValueError as exc:
            raise KeyError(str(exc)) from exc

        # 1. Try built-ins
        if not is_custom_workflow_id(normalized):
            try:
                return self._base_registry.get(normalized)
            except (KeyError, ValueError) as exc:
                raise KeyError(f"Workflow not found: {normalized}") from exc

        # 2. Try custom from store
        try:
            model = self._store.get_definition(normalized)
        except KeyError as exc:
            raise KeyError(f"Workflow not found: {normalized}") from exc

        if model.origin != "custom" or model.status != "active" or model.archived_at is not None:
            raise KeyError(f"Workflow not found or not active: {normalized}")

        return model

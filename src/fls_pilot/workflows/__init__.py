"""Canonical workflow declarations shared by every interface."""

from .registry import (
    CANONICAL_WORKFLOW_IDS,
    DEFAULT_WORKFLOW_REGISTRY,
    WorkflowDeclaration,
    WorkflowRegistry,
    canonical_workflow_id,
)

__all__ = [
    "CANONICAL_WORKFLOW_IDS",
    "DEFAULT_WORKFLOW_REGISTRY",
    "WorkflowDeclaration",
    "WorkflowRegistry",
    "canonical_workflow_id",
]

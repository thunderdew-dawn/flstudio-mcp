"""Workflow Run models."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

@dataclass(frozen=True)
class WorkflowRun:
    """Represents a single execution of a workflow."""
    
    run_id: str
    workflow_id: str
    workflow_version: int
    status: str
    job_id: str | None
    report_id: str | None
    inputs: dict[str, Any] = field(default_factory=dict)
    result: dict[str, Any] | None = None
    error: dict[str, Any] | None = None
    created_at: str = ""
    updated_at: str = ""
    finished_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "workflow_id": self.workflow_id,
            "workflow_version": self.workflow_version,
            "status": self.status,
            "job_id": self.job_id,
            "report_id": self.report_id,
            "inputs": self.inputs,
            "result": self.result,
            "error": self.error,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "finished_at": self.finished_at,
        }

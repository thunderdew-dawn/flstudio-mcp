"""Strict internal Runtime operation registry for daemon RPC."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

RUNTIME_OPERATIONS = {
    "runtime.status",
    "runtime.session",
    "runtime.capabilities",
    "runtime.invalidate",
    "project.current",
    "project.snapshot.get",
    "project.snapshot.refresh",
    "workflow.catalog",
    "workflow.declaration.get",
    "analysis.workflow.run",
    "analysis.live_meter.normalize",
    "analysis.report.add",
    "analysis.report.latest",
    "analysis.report.list",
    "analysis.health.get",
    "job.submit",
    "job.status",
    "job.result",
    "job.cancel",
    "job.list",
}

OPERATION_ALLOWED_PARAMS = {
    "runtime.status": set(),
    "runtime.session": set(),
    "runtime.capabilities": set(),
    "runtime.invalidate": {"event", "workflows"},
    "project.current": set(),
    "project.snapshot.get": {"include_patterns", "include_playlist"},
    "project.snapshot.refresh": {"include_patterns", "include_playlist"},
    "workflow.catalog": {"include_inactive"},
    "workflow.declaration.get": {"workflow_id"},
    "analysis.workflow.run": {"workflow_id", "inputs"},
    "analysis.live_meter.normalize": {
        "policy",
        "watch_status",
        "watch_last_max",
        "static_snapshot",
    },
    "analysis.report.add": {"report"},
    "analysis.report.latest": {"workflow_id"},
    "analysis.report.list": {"workflow_id"},
    "analysis.health.get": set(),
    "job.submit": {
        "kind",
        "input",
        "input_summary",
        "idempotency_key",
        "idempotent",
        "max_retries",
    },
    "job.status": {"job_id"},
    "job.result": {"job_id"},
    "job.cancel": {"job_id"},
    "job.list": {"kind", "status", "limit", "offset"},
}


def validate_runtime_request(request: Mapping[str, Any]) -> tuple[str, dict[str, Any]]:
    if request.get("op") != "runtime":
        raise ValueError("not a Runtime request")
    operation = str(request.get("operation") or "")
    if operation not in RUNTIME_OPERATIONS:
        raise ValueError(f"unknown Runtime operation: {operation!r}")
    raw_params = request.get("params")
    if raw_params is None:
        params: dict[str, Any] = {}
    elif isinstance(raw_params, Mapping):
        params = dict(raw_params)
    else:
        raise ValueError("Runtime params must be an object")
    allowed = OPERATION_ALLOWED_PARAMS[operation]
    unknown = set(params) - allowed
    if unknown:
        raise ValueError(
            f"unsupported params for {operation}: {', '.join(sorted(unknown))}"
        )
    forbidden = {"cmd", "command", "code", "script", "raw"}
    if forbidden.intersection(params):
        raise ValueError("raw command or code fields are forbidden")
    return operation, params

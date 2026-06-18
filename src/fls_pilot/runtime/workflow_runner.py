"""Runtime-owned execution adapters for existing analysis workflows."""

from __future__ import annotations

import threading
from typing import Any

from .core import RuntimeCore


class _WorkflowState:
    def __init__(self, runtime: RuntimeCore) -> None:
        self.lock = threading.RLock()
        self.broker = _RuntimeBrokerFacade(runtime)
        self.report_store = runtime


class _RuntimeBrokerFacade:
    def __init__(self, runtime: RuntimeCore) -> None:
        self._runtime = runtime

    def get_static_project_snapshot(self, bridge, policy=None):  # noqa: ANN001, ANN201
        return self._runtime.get_static_project_snapshot(bridge, policy)

    def get_live_meter_window(self, *args, **kwargs):  # noqa: ANN002, ANN003, ANN201
        return self._runtime.analysis_broker.get_live_meter_window(*args, **kwargs)


def run_workflow(
    runtime: RuntimeCore,
    workflow_id: str,
    *,
    bridge: Any | None,
    inputs: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Execute one declared workflow inside the Runtime process."""
    from .. import control_center
    from .product_workflows import run_product_workflow

    state = _WorkflowState(runtime)
    runners = {
        "mix_review": control_center._run_mix_review,
        "routing_audit": control_center._run_routing_audit,
        "low_end_analysis": control_center._run_low_end_analysis,
        "project_organizer": control_center._run_project_organizer,
    }
    runner = runners.get(workflow_id)
    if runner is None:
        return run_product_workflow(
            runtime,
            workflow_id,
            bridge=bridge,
            inputs=inputs,
        )
    if inputs:
        raise ValueError(f"{workflow_id} does not accept workflow inputs")
    return runner(state, bridge_override=bridge)

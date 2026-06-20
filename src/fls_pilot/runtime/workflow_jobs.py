"""Workflow Jobs orchestration layer.

Connects Workflow definitions and runs to the durable RuntimeJobQueue.
"""

from typing import Any

from .core import RuntimeCore


def submit_workflow_run(
    workflow_id: str,
    inputs: dict[str, Any],
    idempotency_key: str | None = None,
    input_summary: dict[str, Any] | None = None,
    *,
    core: RuntimeCore
) -> dict[str, Any]:
    """Submit a workflow run, backed by a Runtime job."""
    if not isinstance(inputs, dict):
        raise ValueError("inputs must be an object/dict")

    # Load definition (allows custom IDs)
    definition = core.effective_workflows.get_effective(workflow_id)
    
    if definition.runner_type != "job":
        raise ValueError(f"Workflow {workflow_id} has runner_type={definition.runner_type}, expected 'job'")
    if not definition.runner_ref:
        raise ValueError(f"Workflow {workflow_id} has no runner_ref")
    if definition.runner_ref not in core.jobs.list_kinds():
        raise ValueError(f"runner_ref {definition.runner_ref!r} is not a registered job kind")

    # Create run as queued
    run = core.workflow_run_store.create(
        workflow_id=workflow_id,
        workflow_version=definition.version,
        inputs=inputs,
        status="queued"
    )

    # Submit job
    payload = {
        "workflow_id": workflow_id,
        "workflow_version": definition.version,
        "run_id": run.run_id,
        "inputs": inputs
    }
    
    job = core.jobs.submit(
        kind=definition.runner_ref,
        input_payload=payload,
        input_summary=input_summary or {},
        idempotency_key=idempotency_key,
        idempotent=idempotency_key is not None
    )

    # Persist job_id on the run
    run = core.workflow_run_store.update(run.run_id, job_id=job.job_id)
    
    return {"workflow_run": run.to_dict(), "job": job.to_dict()}


def get_workflow_run_status(run_id: str, *, core: RuntimeCore) -> dict[str, Any]:
    """Get the status of a workflow run, deriving state from its backing job if present."""
    run = core.workflow_run_store.get(run_id)
    job_dict = None
    
    if run.job_id:
        try:
            job = core.jobs.status(run.job_id)
            job_dict = job.to_dict()
            
            # Map job status to run status
            status_map = {
                "queued": "queued",
                "running": "running",
                "succeeded": "succeeded",
                "failed": "failed",
                "cancelled": "cancelled"
            }
            new_status = status_map.get(job.status, run.status)
            
            # If changed or if it finished but we haven't marked it yet
            if new_status != run.status or (job.status in ("succeeded", "failed", "cancelled") and not run.finished_at):
                result = None
                error = None
                if job.status == "succeeded":
                    try:
                        # fetch result if available
                        full_job = core.jobs.result(job.job_id)
                        result = full_job.result_ref
                    except Exception:
                        pass
                elif job.status == "failed":
                    error = job.error
                
                run = core.workflow_run_store.update(
                    run.run_id,
                    status=new_status,
                    result=result or run.result,
                    error=error or run.error
                )
        except KeyError:
            # Job might have been deleted, ignore and just use run status
            pass

    return {"workflow_run": run.to_dict(), "job": job_dict}


def list_workflow_runs(
    *,
    workflow_id: str | None = None,
    limit: int = 100,
    include_finished: bool = True,
    core: RuntimeCore
) -> list[dict[str, Any]]:
    """List workflow runs."""
    # Ensure reasonable bounds
    limit = min(max(1, limit), 1000)
    
    runs = core.workflow_run_store.list(
        workflow_id=workflow_id,
        limit=limit,
        include_finished=include_finished
    )
    return [run.to_dict() for run in runs]


def cancel_workflow_run(run_id: str, *, core: RuntimeCore) -> dict[str, Any]:
    """Best-effort cancel of a workflow run and its backing job."""
    run = core.workflow_run_store.get(run_id)
    job_dict = None
    
    if run.job_id:
        try:
            job = core.jobs.cancel(run.job_id)
            job_dict = job.to_dict()
            
            if run.status not in ("succeeded", "failed", "cancelled"):
                run = core.workflow_run_store.update(run.run_id, status="cancelled")
        except KeyError:
            # Job not found
            if run.status not in ("succeeded", "failed", "cancelled"):
                run = core.workflow_run_store.update(run.run_id, status="cancelled")
    else:
        if run.status not in ("succeeded", "failed", "cancelled"):
            run = core.workflow_run_store.update(run.run_id, status="cancelled")
            
    return {"workflow_run": run.to_dict(), "job": job_dict}

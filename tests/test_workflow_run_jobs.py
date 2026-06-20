import time
import pytest

from fls_pilot.runtime.core import RuntimeCore
from fls_pilot.runtime.workflow_jobs import (
    submit_workflow_run,
    get_workflow_run_status,
    cancel_workflow_run,
)

def test_workflow_run_jobs_submit_and_status(tmp_path):
    core = RuntimeCore(
        workflow_store_path=tmp_path / "workflows.sqlite3",
        job_store_path=tmp_path / "jobs.sqlite3",
        workflow_run_store_path=tmp_path / "runs.sqlite3",
    )
    
    # Register job handler
    core.register_job_handler("test.echo", lambda payload, ctx: {"value": payload.get("inputs", {}).get("value")})
    
    # Add workflow definition
    definition_payload = {
        "workflow_id": "user.test_job_wf",
        "title": "Test Job WF",
        "kind": "analysis_workflow",
        "status": "active",
        "runner_type": "job",
        "runner_ref": "test.echo",
        "analysis_report_required": False,
        "health_inclusion_policy": "optional_context_report",
        "inputs_schema": {},
        "metadata": {}
    }
    core.workflow_store.create_custom(definition_payload, valid_job_kinds=("test.echo",))
    
    try:
        # Submit workflow run
        result = submit_workflow_run("user.test_job_wf", inputs={"value": 42}, core=core)
        run = result["workflow_run"]
        job = result["job"]
        
        assert run["workflow_id"] == "user.test_job_wf"
        assert run["status"] == "queued"
        assert run["job_id"] == job["job_id"]
        assert job["kind"] == "test.echo"
        # Wait for job to finish
        deadline = time.monotonic() + 2.0
        succeeded = False
        while time.monotonic() < deadline:
            status_result = get_workflow_run_status(run["run_id"], core=core)
            if status_result["workflow_run"]["status"] == "succeeded":
                succeeded = True
                break
            time.sleep(0.01)
            
        assert succeeded, "Workflow run did not succeed"
        assert status_result["job"]["status"] == "succeeded"
        assert status_result["workflow_run"]["result"] is not None
        assert status_result["workflow_run"]["result"]["value"] == 42
    finally:
        core.close()


def test_workflow_run_jobs_invalid_submit(tmp_path):
    core = RuntimeCore(
        workflow_store_path=tmp_path / "workflows.sqlite3",
        job_store_path=tmp_path / "jobs.sqlite3",
        workflow_run_store_path=tmp_path / "runs.sqlite3",
    )
    
    try:
        # Unknown workflow
        with pytest.raises(KeyError):
            submit_workflow_run("user.unknown", inputs={}, core=core)
            
        # Create workflow with runner_type != 'job'
        core.workflow_store.create_custom({
            "workflow_id": "user.not_job",
            "title": "Not Job",
            "kind": "analysis_workflow",
            "status": "active",
            "runner_type": "builtin",
            "runner_ref": "some_builtin",
            "analysis_report_required": False,
            "health_inclusion_policy": "none",
            "inputs_schema": {},
            "metadata": {}
        }, valid_job_kinds=())
        
        with pytest.raises(ValueError, match="expected 'job'"):
            submit_workflow_run("user.not_job", inputs={}, core=core)
    finally:
        core.close()


def test_workflow_run_cancel(tmp_path):
    core = RuntimeCore(
        workflow_store_path=tmp_path / "workflows.sqlite3",
        job_store_path=tmp_path / "jobs.sqlite3",
        workflow_run_store_path=tmp_path / "runs.sqlite3",
    )
    
    core.register_job_handler("test.slow", lambda payload, ctx: time.sleep(0.5))
    core.workflow_store.create_custom({
        "workflow_id": "user.slow_wf",
        "title": "Slow",
        "kind": "analysis",
        "status": "active",
        "runner_type": "job",
        "runner_ref": "test.slow",
        "analysis_report_required": False,
        "health_inclusion_policy": "none",
        "inputs_schema": {},
        "metadata": {}
    }, valid_job_kinds=("test.slow",))
    
    try:
        result = submit_workflow_run("user.slow_wf", inputs={}, core=core)
        run_id = result["workflow_run"]["run_id"]
        
        cancel_result = cancel_workflow_run(run_id, core=core)
        assert cancel_result["workflow_run"]["status"] == "cancelled"
        assert cancel_result["job"]["cancel_requested"] is True
    finally:
        core.close()

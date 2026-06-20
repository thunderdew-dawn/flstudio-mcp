import json
import sqlite3
import pytest
from fls_pilot.runtime.workflow_run_store import WorkflowRunStore

def test_workflow_run_store_init(tmp_path):
    db_path = tmp_path / "runs.sqlite3"
    store = WorkflowRunStore(db_path)
    assert db_path.exists()
    
    with sqlite3.connect(db_path) as conn:
        cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='workflow_runs'")
        assert cursor.fetchone() is not None

def test_workflow_run_crud(tmp_path):
    store = WorkflowRunStore(tmp_path / "runs.sqlite3")
    
    run = store.create(
        workflow_id="user.test_wf",
        workflow_version=1,
        inputs={"foo": "bar"},
        status="queued"
    )
    
    assert run.workflow_id == "user.test_wf"
    assert run.status == "queued"
    assert run.inputs == {"foo": "bar"}
    assert run.job_id is None
    
    # Read
    read_run = store.get(run.run_id)
    assert read_run.run_id == run.run_id
    
    # Update job_id
    updated = store.update(run.run_id, job_id="job_123", status="running")
    assert updated.job_id == "job_123"
    assert updated.status == "running"
    
    # Mark finished
    finished = store.update(run.run_id, status="succeeded", result={"score": 100})
    assert finished.status == "succeeded"
    assert finished.result == {"score": 100}
    assert finished.finished_at is not None

def test_workflow_run_list(tmp_path):
    store = WorkflowRunStore(tmp_path / "runs.sqlite3")
    
    run1 = store.create("user.wf1", 1, {})
    run2 = store.create("user.wf2", 1, {})
    run3 = store.create("user.wf1", 2, {}, status="succeeded")
    store.update(run3.run_id, status="succeeded")
    
    # Filter by workflow_id
    wf1_runs = store.list(workflow_id="user.wf1")
    assert len(wf1_runs) == 2
    
    # Filter finished
    active_runs = store.list(include_finished=False)
    assert len(active_runs) == 2
    for r in active_runs:
        assert r.status != "succeeded"
        
    # Limit
    limited = store.list(limit=1)
    assert len(limited) == 1

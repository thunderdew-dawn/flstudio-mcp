"""Tests for WorkflowStore."""

import sqlite3
import pytest

from fls_pilot.runtime.workflow_models import WorkflowDefinition
from fls_pilot.runtime.workflow_store import WorkflowStore
from fls_pilot.workflows.registry import DEFAULT_WORKFLOW_REGISTRY


@pytest.fixture
def memory_db(tmp_path):
    return str(tmp_path / "workflows.sqlite")


@pytest.fixture
def store(memory_db):
    return WorkflowStore(memory_db)


def test_store_initializes_sqlite(memory_db):
    store = WorkflowStore(memory_db)
    with sqlite3.connect(memory_db) as conn:
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='workflow_definitions'"
        )
        assert cursor.fetchone() is not None


def test_mirror_builtins(store):
    versions = store.mirror_builtins(DEFAULT_WORKFLOW_REGISTRY)
    assert versions
    
    definitions = store.list_definitions(include_archived=True)
    assert len(definitions) == len(DEFAULT_WORKFLOW_REGISTRY.list(include_inactive=True))
    
    for decl in DEFAULT_WORKFLOW_REGISTRY.list(include_inactive=True):
        assert decl.id in versions
        
        # Verify definitions maintain stability and correct protected properties
        db_def = store.get_definition(decl.id)
        assert db_def.workflow_id == decl.id
        assert db_def.origin == "builtin"
        assert db_def.protected is True
        assert db_def.runner_type == "builtin"
        assert db_def.runner_ref == decl.id
        assert db_def.analysis_report_required == decl.analysis_report_required


def test_mirror_builtins_is_idempotent(store):
    # First mirror
    versions1 = store.mirror_builtins(DEFAULT_WORKFLOW_REGISTRY)
    definitions1 = store.list_definitions(include_archived=True)
    
    # Second mirror
    versions2 = store.mirror_builtins(DEFAULT_WORKFLOW_REGISTRY)
    definitions2 = store.list_definitions(include_archived=True)
    
    assert versions1 == versions2
    assert len(definitions1) == len(definitions2)
    
    # Verify no duplicates in table
    with sqlite3.connect(store._db_path) as conn:
        cursor = conn.execute("SELECT workflow_id, COUNT(*) FROM workflow_definitions GROUP BY workflow_id")
        for row in cursor:
            assert row[1] == 1, f"Expected 1 version for {row[0]}, got {row[1]}"


def test_list_and_get_definitions(store):
    store.mirror_builtins(DEFAULT_WORKFLOW_REGISTRY)
    
    # Fetch all
    defs = store.list_definitions()
    
    # get specific one
    mix_review = store.get_definition("mix_review")
    assert mix_review.title == "Mix Review"
    assert mix_review.kind == "analysis_workflow"
    assert mix_review.status == "active"
    assert mix_review.protected is True
    
    # get with version
    mix_review_v1 = store.get_definition("mix_review", version=1)
    assert mix_review_v1.version == 1

def test_missing_definition_raises(store):
    with pytest.raises(KeyError):
        store.get_definition("non_existent_workflow")

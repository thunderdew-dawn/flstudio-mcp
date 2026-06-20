from __future__ import annotations

import json
import pytest
from datetime import datetime, timezone

from fls_pilot.runtime.effective_workflows import EffectiveWorkflowRegistry
from fls_pilot.runtime.workflow_store import WorkflowStore
from fls_pilot.workflows.registry import DEFAULT_WORKFLOW_REGISTRY


@pytest.fixture
def empty_store(tmp_path) -> WorkflowStore:
    db_path = tmp_path / "workflows.sqlite"
    return WorkflowStore(str(db_path))


@pytest.fixture
def store_with_customs(empty_store: WorkflowStore) -> WorkflowStore:
    # Insert custom workflows directly into the store for testing
    now = datetime.now(timezone.utc).isoformat()
    payload = json.dumps({
        "description": "Test",
        "analysis_report_required": True,
        "health_inclusion_policy": "optional_context_report"
    })
    
    with __import__('sqlite3').connect(empty_store._db_path) as conn:
        # 1. Active custom definition
        conn.execute(
            """
            INSERT INTO workflow_definitions (
                workflow_id, version, title, kind, status, origin,
                protected, runner_type, runner_ref, payload_json,
                created_at, updated_at, archived_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("user.low_end_level4", 1, "Level 4", "analysis_workflow", "active", "custom",
             0, "job", "workflow.low_end_level4", payload, now, now, None)
        )
        # 2. Archived custom definition
        conn.execute(
            """
            INSERT INTO workflow_definitions (
                workflow_id, version, title, kind, status, origin,
                protected, runner_type, runner_ref, payload_json,
                created_at, updated_at, archived_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("user.old_workflow", 1, "Old", "analysis_workflow", "active", "custom",
             0, "job", "workflow.old", payload, now, now, now)
        )
        # 3. Custom definition attempting to override builtin
        conn.execute(
            """
            INSERT INTO workflow_definitions (
                workflow_id, version, title, kind, status, origin,
                protected, runner_type, runner_ref, payload_json,
                created_at, updated_at, archived_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("low_end_analysis", 1, "Fake Low End", "analysis_workflow", "active", "custom",
             0, "job", "workflow.fake", payload, now, now, None)
        )
        # 4. Custom definition with invalid ID
        conn.execute(
            """
            INSERT INTO workflow_definitions (
                workflow_id, version, title, kind, status, origin,
                protected, runner_type, runner_ref, payload_json,
                created_at, updated_at, archived_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("invalid/workflow", 1, "Invalid", "analysis_workflow", "active", "custom",
             0, "job", "workflow.invalid", payload, now, now, None)
        )
        
    return empty_store


def test_effective_registry_empty_store_preserves_builtins(empty_store: WorkflowStore) -> None:
    registry = EffectiveWorkflowRegistry(DEFAULT_WORKFLOW_REGISTRY, empty_store)
    effective_list = registry.list_effective()
    
    builtin_list = DEFAULT_WORKFLOW_REGISTRY.list(include_inactive=True)
    assert len(effective_list) == len(builtin_list)
    assert {row.id for row in effective_list} == {row.id for row in builtin_list}
    
    assert registry.get_effective("low-end").id == "low_end_analysis"


def test_effective_registry_includes_active_customs(store_with_customs: WorkflowStore) -> None:
    registry = EffectiveWorkflowRegistry(DEFAULT_WORKFLOW_REGISTRY, store_with_customs)
    effective_list = registry.list_effective()
    
    ids = {getattr(row, "id", getattr(row, "workflow_id", None)) for row in effective_list}
    
    # Active custom is included
    assert "user.low_end_level4" in ids
    
    # Archived custom is excluded
    assert "user.old_workflow" not in ids
    
    # Invalid custom ID is excluded
    assert "invalid/workflow" not in ids
    
    # Built-in is preserved, override is ignored
    low_end = registry.get_effective("low_end_analysis")
    assert getattr(low_end, "title") == "Low-End Safety Check"  # The builtin title


def test_effective_registry_get_effective(store_with_customs: WorkflowStore) -> None:
    registry = EffectiveWorkflowRegistry(DEFAULT_WORKFLOW_REGISTRY, store_with_customs)
    
    # Get builtin
    builtin = registry.get_effective("mix_review")
    assert builtin.id == "mix_review"
    
    # Get custom
    custom = registry.get_effective("user.low_end_level4")
    assert custom.workflow_id == "user.low_end_level4"
    assert custom.title == "Level 4"
    
    # Get archived custom raises KeyError
    with pytest.raises(KeyError):
        registry.get_effective("user.old_workflow")
        
    # Get unknown raises KeyError
    with pytest.raises(KeyError):
        registry.get_effective("user.unknown")

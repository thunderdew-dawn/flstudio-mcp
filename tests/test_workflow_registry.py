from __future__ import annotations

import pytest

from fls_pilot.workflows.registry import (
    DEFAULT_WORKFLOW_REGISTRY,
    WorkflowDeclaration,
    WorkflowRegistry,
    canonical_workflow_id,
)


def test_legacy_ids_canonicalize() -> None:
    assert canonical_workflow_id("low-end") == "low_end_analysis"
    assert canonical_workflow_id("organizer") == "project_organizer"
    assert canonical_workflow_id("sidechaining") == "sidechain_routing_check"


def test_registry_rejects_duplicate_ids() -> None:
    row = DEFAULT_WORKFLOW_REGISTRY.get("mix_review")
    with pytest.raises(ValueError, match="duplicate workflow id"):
        WorkflowRegistry((row, row))


def test_declaration_rejects_invalid_health_policy() -> None:
    with pytest.raises(ValueError, match="health inclusion"):
        WorkflowDeclaration(
            id="mix_review",
            title="Mix",
            kind="analysis_workflow",
            status="active",
            health_inclusion_policy="private_policy",
            analysis_report_required=True,
        )


def test_default_catalog_uses_canonical_ids_and_backend_health() -> None:
    catalog = {
        row["id"]: row for row in DEFAULT_WORKFLOW_REGISTRY.control_center_catalog()
    }
    assert catalog["project_health"]["endpoint"] == "/api/workflows/project-health"
    assert catalog["preflight"]["enabled"] is True
    assert catalog["sidechain_routing_check"]["enabled"] is False
    assert catalog["sidechain_routing_check"]["endpoint"] is None
    assert catalog["plugin_assistant"]["enabled"] is False
    assert catalog["plugin_assistant"]["health_inclusion_policy"] == "excluded"
    assert catalog["jam_2_project"]["enabled"] is False
    assert catalog["jam_2_project"]["group"] == "Roadmap"
    assert "sidechaining" not in catalog

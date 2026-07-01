from __future__ import annotations

import pytest

from fls_pilot.packs import load_pack_manifest
from fls_pilot.workflows.registry import (
    DEFAULT_WORKFLOW_REGISTRY,
    WorkflowDeclaration,
    WorkflowRegistry,
    build_effective_workflow_registry,
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


def test_level_two_workflows_declare_optional_live_meter_window() -> None:
    for workflow_id in ("mix_review", "low_end_analysis", "preflight"):
        requirements = DEFAULT_WORKFLOW_REGISTRY.get(workflow_id).requirements
        assert requirements is not None
        optional_ids = {row.id for row in requirements.optional}
        assert "live_meter_window" in optional_ids


def test_effective_registry_attaches_pack_metadata_without_overriding_core() -> None:
    base = DEFAULT_WORKFLOW_REGISTRY.get("low_end_analysis")
    manifest = load_pack_manifest(
        {
            "pack_id": "genre.house",
            "version": "1.0.0",
            "title": "House Pack",
            "publisher": "FLS Pilot",
            "min_app_version": "3.0.0b3",
            "workflows": [
                {
                    "workflow_id": "low_end_analysis",
                    "profiles": ["house"],
                    "metadata": {"genre": "house", "badge": "genre"},
                }
            ],
            "rulesets": [],
            "profiles": [{"id": "house", "title": "House"}],
            "entitlement": {"kind": "pro"},
            "metadata": {},
        }
    )

    effective = build_effective_workflow_registry(
        DEFAULT_WORKFLOW_REGISTRY,
        (manifest,),
    )
    extended = effective.get("low_end_analysis")
    pack = extended.metadata["pack_extensions"][0]

    assert effective.get("mix_review") is DEFAULT_WORKFLOW_REGISTRY.get("mix_review")
    assert extended.endpoint == base.endpoint
    assert extended.requirements == base.requirements
    assert extended.safety_note == base.safety_note
    assert extended.forbidden_actions == base.forbidden_actions
    assert pack["pack_id"] == "genre.house"
    assert pack["entitlement"] == {"kind": "pro"}
    assert pack["profiles"] == [{"id": "house", "title": "House"}]
    assert pack["metadata"]["genre"] == "house"


def test_effective_registry_rejects_unknown_pack_profile() -> None:
    manifest = load_pack_manifest(
        {
            "pack_id": "genre.house",
            "version": "1.0.0",
            "title": "House Pack",
            "publisher": "FLS Pilot",
            "min_app_version": "3.0.0b3",
            "workflows": [
                {
                    "workflow_id": "low_end_analysis",
                    "profiles": ["missing"],
                    "metadata": {},
                }
            ],
            "rulesets": [],
            "profiles": [],
            "entitlement": {"kind": "free"},
            "metadata": {},
        }
    )

    with pytest.raises(ValueError, match="unknown profile id"):
        build_effective_workflow_registry(DEFAULT_WORKFLOW_REGISTRY, (manifest,))


def test_effective_registry_without_packs_preserves_base_output() -> None:
    effective = build_effective_workflow_registry(DEFAULT_WORKFLOW_REGISTRY, ())

    assert [row.to_dict() for row in effective.list()] == [
        row.to_dict() for row in DEFAULT_WORKFLOW_REGISTRY.list()
    ]

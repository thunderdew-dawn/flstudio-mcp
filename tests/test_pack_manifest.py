from __future__ import annotations

import pytest

from fls_pilot.packs import PackEntitlement, load_pack_manifest


def _manifest_payload() -> dict:
    return {
        "pack_id": "genre.house",
        "version": "1.0.0",
        "title": "House Production Pack",
        "publisher": "FLS Pilot",
        "min_app_version": "3.0.0rc1",
        "workflows": [
            {
                "workflow_id": "low_end_analysis",
                "profiles": ["house"],
                "metadata": {"genre": "house", "badge": "genre"},
            }
        ],
        "rulesets": [{"id": "house.low-end", "version": "1.0.0"}],
        "profiles": [{"id": "house", "title": "House"}],
        "entitlement": {"kind": "free"},
        "metadata": {"description": "House-focused workflow metadata."},
    }


def test_valid_pack_manifest_round_trips_deterministically() -> None:
    payload = _manifest_payload()

    manifest = load_pack_manifest(payload)

    assert manifest.to_dict() == payload
    assert manifest.workflows[0].workflow_id == "low_end_analysis"
    assert manifest.metadata["description"].startswith("House")


def test_missing_required_pack_manifest_field_fails() -> None:
    payload = _manifest_payload()
    payload.pop("publisher")

    with pytest.raises(ValueError, match="publisher"):
        load_pack_manifest(payload)


def test_unknown_pack_workflow_id_fails() -> None:
    payload = _manifest_payload()
    payload["workflows"][0]["workflow_id"] = "remote_mastering"

    with pytest.raises(ValueError, match="unknown workflow id"):
        load_pack_manifest(payload)


@pytest.mark.parametrize(
    "field",
    [
        "endpoint",
        "requirements",
        "safety_note",
        "forbidden_actions",
        "write_operations",
    ],
)
def test_pack_workflow_metadata_cannot_override_protected_fields(field: str) -> None:
    payload = _manifest_payload()
    payload["workflows"][0]["metadata"][field] = "unsafe"

    with pytest.raises(ValueError, match="protected fields"):
        load_pack_manifest(payload)


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        ({"kind": "free"}, {"kind": "free"}),
        ({"kind": "pro"}, {"kind": "pro"}),
        (
            {"kind": "sku", "sku": "fls.genre.house"},
            {"kind": "sku", "sku": "fls.genre.house"},
        ),
    ],
)
def test_pack_entitlement_supports_free_pro_and_sku(
    payload: dict,
    expected: dict,
) -> None:
    assert PackEntitlement(**payload).to_dict() == expected


def test_sku_entitlement_requires_sku() -> None:
    with pytest.raises(ValueError, match="requires sku"):
        PackEntitlement(kind="sku")

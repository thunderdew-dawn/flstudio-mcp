from __future__ import annotations

import json
from pathlib import Path

from fls_pilot.packs.manager import (
    PACK_STATE_FILE,
    disable_pack,
    enable_pack,
    list_installed_packs,
    load_installed_manifests,
)


def _manifest(pack_id: str, *, workflow_id: str = "low_end_analysis") -> dict:
    return {
        "pack_id": pack_id,
        "version": "1.0.0",
        "title": pack_id,
        "publisher": "FLS Pilot",
        "min_app_version": "3.0.0b3",
        "workflows": [
            {
                "workflow_id": workflow_id,
                "profiles": [],
                "metadata": {},
            }
        ],
        "rulesets": [],
        "profiles": [],
        "entitlement": {"kind": "free"},
        "metadata": {},
    }


def _write_manifest(root: Path, directory: str, payload: dict) -> None:
    pack_dir = root / directory
    pack_dir.mkdir(parents=True)
    (pack_dir / "manifest.json").write_text(
        json.dumps(payload),
        "utf-8",
    )


def test_pack_manager_lists_and_loads_valid_local_manifests(tmp_path) -> None:
    _write_manifest(tmp_path, "z-pack", _manifest("pack.z"))
    _write_manifest(tmp_path, "a-pack", _manifest("pack.a"))

    rows = list_installed_packs(tmp_path)
    manifests = load_installed_manifests(tmp_path)

    assert [row["pack_id"] for row in rows] == ["pack.a", "pack.z"]
    assert all(row["enabled"] for row in rows)
    assert [manifest.pack_id for manifest in manifests] == ["pack.a", "pack.z"]


def test_disabled_pack_is_excluded_from_effective_manifests(tmp_path) -> None:
    _write_manifest(tmp_path, "house", _manifest("genre.house"))

    result = disable_pack("genre.house", tmp_path)

    assert result == {"pack_id": "genre.house", "enabled": False}
    assert load_installed_manifests(tmp_path) == ()
    assert list_installed_packs(tmp_path)[0]["enabled"] is False
    assert json.loads((tmp_path / PACK_STATE_FILE).read_text("utf-8")) == {
        "disabled_pack_ids": ["genre.house"]
    }

    assert enable_pack("genre.house", tmp_path) == {
        "pack_id": "genre.house",
        "enabled": True,
    }
    assert [manifest.pack_id for manifest in load_installed_manifests(tmp_path)] == [
        "genre.house"
    ]


def test_invalid_pack_is_reported_and_ignored(tmp_path) -> None:
    _write_manifest(tmp_path, "broken", {"pack_id": "broken"})

    rows = list_installed_packs(tmp_path)

    assert rows[0]["status"] == "invalid"
    assert rows[0]["enabled"] is False
    assert "missing required manifest fields" in rows[0]["error"]
    assert load_installed_manifests(tmp_path) == ()


def test_pack_manager_does_not_follow_symlinked_pack_directories(tmp_path) -> None:
    outside = tmp_path / "outside"
    _write_manifest(outside, "linked", _manifest("linked.pack"))
    pack_root = tmp_path / "packs"
    pack_root.mkdir()
    (pack_root / "linked").symlink_to(outside / "linked", target_is_directory=True)

    assert list_installed_packs(pack_root) == ()
    assert load_installed_manifests(pack_root) == ()

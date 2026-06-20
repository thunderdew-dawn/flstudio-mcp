"""Local manifest discovery and deterministic pack enablement state."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from .manifest import PackManifest, load_pack_manifest

DEFAULT_PACKS_DIR = Path.home() / ".fls-pilot" / "packs"
PACK_STATE_FILE = ".pack-state.json"
PACK_MANIFEST_FILE = "manifest.json"


def list_installed_packs(root: str | Path | None = None) -> tuple[dict[str, Any], ...]:
    """List valid and invalid local pack directories without executing pack code."""
    pack_root = _pack_root(root)
    disabled = _disabled_pack_ids(pack_root)
    rows: list[dict[str, Any]] = []
    seen_pack_ids: set[str] = set()
    if not pack_root.exists():
        return ()

    for directory in sorted(pack_root.iterdir(), key=lambda path: path.name):
        if not directory.is_dir() or directory.is_symlink():
            continue
        manifest_path = directory / PACK_MANIFEST_FILE
        if not manifest_path.is_file() or manifest_path.is_symlink():
            continue
        try:
            manifest = _load_manifest_file(manifest_path)
            if manifest.pack_id in seen_pack_ids:
                raise ValueError(f"duplicate installed pack id: {manifest.pack_id}")
            seen_pack_ids.add(manifest.pack_id)
            rows.append(
                {
                    "pack_id": manifest.pack_id,
                    "version": manifest.version,
                    "title": manifest.title,
                    "path": str(directory),
                    "enabled": manifest.pack_id not in disabled,
                    "status": "valid",
                    "error": None,
                }
            )
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            rows.append(
                {
                    "pack_id": directory.name,
                    "version": None,
                    "title": directory.name,
                    "path": str(directory),
                    "enabled": False,
                    "status": "invalid",
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )
    return tuple(rows)


def load_installed_manifests(
    root: str | Path | None = None,
) -> tuple[PackManifest, ...]:
    """Load enabled valid manifests in deterministic pack-id order."""
    pack_root = _pack_root(root)
    disabled = _disabled_pack_ids(pack_root)
    manifests: dict[str, PackManifest] = {}
    if not pack_root.exists():
        return ()

    for directory in sorted(pack_root.iterdir(), key=lambda path: path.name):
        if not directory.is_dir() or directory.is_symlink():
            continue
        manifest_path = directory / PACK_MANIFEST_FILE
        if not manifest_path.is_file() or manifest_path.is_symlink():
            continue
        try:
            manifest = _load_manifest_file(manifest_path)
        except (OSError, ValueError, json.JSONDecodeError):
            continue
        if manifest.pack_id in disabled or manifest.pack_id in manifests:
            continue
        manifests[manifest.pack_id] = manifest
    return tuple(manifests[pack_id] for pack_id in sorted(manifests))


def enable_pack(
    pack_id: str,
    root: str | Path | None = None,
) -> dict[str, Any]:
    """Enable one installed valid local pack."""
    pack_root = _pack_root(root)
    normalized = _installed_pack_id(pack_id, pack_root)
    disabled = _disabled_pack_ids(pack_root)
    disabled.discard(normalized)
    _write_pack_state(pack_root, disabled)
    return {"pack_id": normalized, "enabled": True}


def disable_pack(
    pack_id: str,
    root: str | Path | None = None,
) -> dict[str, Any]:
    """Disable one installed valid local pack."""
    pack_root = _pack_root(root)
    normalized = _installed_pack_id(pack_id, pack_root)
    disabled = _disabled_pack_ids(pack_root)
    disabled.add(normalized)
    _write_pack_state(pack_root, disabled)
    return {"pack_id": normalized, "enabled": False}


def _pack_root(root: str | Path | None) -> Path:
    if root is not None:
        return Path(root).expanduser()
    configured = os.environ.get("FLS_PILOT_PACKS_DIR")
    return Path(configured).expanduser() if configured else DEFAULT_PACKS_DIR


def _load_manifest_file(path: Path) -> PackManifest:
    payload = json.loads(path.read_text("utf-8"))
    return load_pack_manifest(payload)


def _disabled_pack_ids(root: Path) -> set[str]:
    state_path = root / PACK_STATE_FILE
    if not state_path.is_file() or state_path.is_symlink():
        return set()
    try:
        payload = json.loads(state_path.read_text("utf-8"))
    except (OSError, json.JSONDecodeError):
        return set()
    rows = payload.get("disabled_pack_ids") if isinstance(payload, dict) else ()
    if not isinstance(rows, list):
        return set()
    return {str(item) for item in rows if str(item).strip()}


def _installed_pack_id(pack_id: str, root: Path) -> str:
    normalized = str(pack_id or "").strip()
    if not normalized:
        raise ValueError("pack_id is required")
    valid_ids = {
        row["pack_id"]
        for row in list_installed_packs(root)
        if row["status"] == "valid"
    }
    if normalized not in valid_ids:
        raise ValueError(f"unknown or invalid installed pack: {normalized}")
    return normalized


def _write_pack_state(root: Path, disabled_pack_ids: set[str]) -> None:
    root.mkdir(parents=True, exist_ok=True)
    state_path = root / PACK_STATE_FILE
    temp_path = root / f"{PACK_STATE_FILE}.tmp"
    payload = {
        "disabled_pack_ids": sorted(disabled_pack_ids),
    }
    temp_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        "utf-8",
    )
    temp_path.replace(state_path)

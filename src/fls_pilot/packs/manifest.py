"""Validated data-only manifests for local workflow packs."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..workflow_identity import canonical_workflow_id

ENTITLEMENT_KINDS = {"free", "pro", "sku"}
REQUIRED_MANIFEST_FIELDS = {
    "pack_id",
    "version",
    "title",
    "publisher",
    "min_app_version",
    "workflows",
    "rulesets",
    "profiles",
    "entitlement",
    "metadata",
}
FORBIDDEN_WORKFLOW_METADATA_FIELDS = {
    "endpoint",
    "requirements",
    "safety_note",
    "supported_next_actions",
    "manual_only_actions",
    "forbidden_actions",
    "write_operations",
}


def _required_text(value: Any, field_name: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise ValueError(f"{field_name} is required")
    return normalized


def _dict(value: Any, field_name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{field_name} must be an object")
    return {str(key): item for key, item in value.items()}


def _dict_rows(value: Any, field_name: str) -> tuple[dict[str, Any], ...]:
    if not isinstance(value, (list, tuple)):
        raise ValueError(f"{field_name} must be an array")
    rows: list[dict[str, Any]] = []
    for index, item in enumerate(value):
        rows.append(_dict(item, f"{field_name}[{index}]"))
    return tuple(rows)


@dataclass(frozen=True)
class PackWorkflowExtension:
    """Metadata attached to one canonical core workflow."""

    workflow_id: str
    profiles: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "workflow_id", canonical_workflow_id(self.workflow_id))
        object.__setattr__(
            self,
            "profiles",
            tuple(_required_text(item, "workflow profile") for item in self.profiles),
        )
        metadata = dict(self.metadata)
        forbidden = sorted(FORBIDDEN_WORKFLOW_METADATA_FIELDS & metadata.keys())
        if forbidden:
            raise ValueError(
                "workflow metadata cannot override protected fields: "
                + ", ".join(forbidden)
            )
        object.__setattr__(self, "metadata", metadata)

    def to_dict(self) -> dict[str, Any]:
        return {
            "workflow_id": self.workflow_id,
            "profiles": list(self.profiles),
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class PackEntitlement:
    """Display-only entitlement metadata."""

    kind: str
    sku: str | None = None

    def __post_init__(self) -> None:
        kind = str(self.kind or "").strip().lower()
        if kind not in ENTITLEMENT_KINDS:
            raise ValueError(f"invalid entitlement kind: {self.kind!r}")
        sku = str(self.sku or "").strip() or None
        if kind == "sku" and sku is None:
            raise ValueError("sku entitlement requires sku")
        if kind != "sku" and sku is not None:
            raise ValueError(f"{kind} entitlement cannot define sku")
        object.__setattr__(self, "kind", kind)
        object.__setattr__(self, "sku", sku)

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"kind": self.kind}
        if self.sku is not None:
            out["sku"] = self.sku
        return out


@dataclass(frozen=True)
class PackManifest:
    """A local pack manifest that contains data but no executable code."""

    pack_id: str
    version: str
    title: str
    publisher: str
    min_app_version: str
    workflows: tuple[PackWorkflowExtension, ...]
    rulesets: tuple[dict[str, Any], ...]
    profiles: tuple[dict[str, Any], ...]
    entitlement: PackEntitlement
    metadata: dict[str, Any]

    def __post_init__(self) -> None:
        for field_name in (
            "pack_id",
            "version",
            "title",
            "publisher",
            "min_app_version",
        ):
            object.__setattr__(
                self,
                field_name,
                _required_text(getattr(self, field_name), field_name),
            )
        object.__setattr__(self, "workflows", tuple(self.workflows))
        object.__setattr__(
            self,
            "rulesets",
            tuple(dict(item) for item in self.rulesets),
        )
        object.__setattr__(
            self,
            "profiles",
            tuple(dict(item) for item in self.profiles),
        )
        object.__setattr__(self, "metadata", dict(self.metadata))

    def to_dict(self) -> dict[str, Any]:
        return {
            "pack_id": self.pack_id,
            "version": self.version,
            "title": self.title,
            "publisher": self.publisher,
            "min_app_version": self.min_app_version,
            "workflows": [item.to_dict() for item in self.workflows],
            "rulesets": [dict(item) for item in self.rulesets],
            "profiles": [dict(item) for item in self.profiles],
            "entitlement": self.entitlement.to_dict(),
            "metadata": dict(self.metadata),
        }


def load_pack_manifest(payload: dict[str, Any]) -> PackManifest:
    """Parse and validate one in-memory pack manifest."""
    if not isinstance(payload, dict):
        raise ValueError("pack manifest must be an object")
    missing = sorted(REQUIRED_MANIFEST_FIELDS - payload.keys())
    if missing:
        raise ValueError(f"missing required manifest fields: {', '.join(missing)}")

    workflow_rows = payload["workflows"]
    if not isinstance(workflow_rows, (list, tuple)):
        raise ValueError("workflows must be an array")
    workflows = tuple(
        _load_workflow_extension(item, index)
        for index, item in enumerate(workflow_rows)
    )

    entitlement_payload = _dict(payload["entitlement"], "entitlement")
    return PackManifest(
        pack_id=_required_text(payload["pack_id"], "pack_id"),
        version=_required_text(payload["version"], "version"),
        title=_required_text(payload["title"], "title"),
        publisher=_required_text(payload["publisher"], "publisher"),
        min_app_version=_required_text(
            payload["min_app_version"],
            "min_app_version",
        ),
        workflows=workflows,
        rulesets=_dict_rows(payload["rulesets"], "rulesets"),
        profiles=_dict_rows(payload["profiles"], "profiles"),
        entitlement=PackEntitlement(
            kind=entitlement_payload.get("kind", ""),
            sku=entitlement_payload.get("sku"),
        ),
        metadata=_dict(payload["metadata"], "metadata"),
    )


def _load_workflow_extension(value: Any, index: int) -> PackWorkflowExtension:
    payload = _dict(value, f"workflows[{index}]")
    profiles = payload.get("profiles", ())
    if not isinstance(profiles, (list, tuple)):
        raise ValueError(f"workflows[{index}].profiles must be an array")
    return PackWorkflowExtension(
        workflow_id=_required_text(
            payload.get("workflow_id"),
            f"workflows[{index}].workflow_id",
        ),
        profiles=tuple(profiles),
        metadata=_dict(payload.get("metadata", {}), f"workflows[{index}].metadata"),
    )

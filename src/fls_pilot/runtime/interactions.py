"""Serializable user-interaction requests emitted by workflows."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

INTERACTION_TYPES = {"multi_select", "single_select", "confirm", "manual_task"}
MANUAL_AUDIO_EXTENSIONS = (".wav", ".aiff", ".flac")


def _required_text(value: Any, field_name: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise ValueError(f"{field_name} is required")
    return normalized


@dataclass(frozen=True)
class InteractionRequest:
    id: str
    type: str
    prompt: str
    options: tuple[dict[str, Any], ...] = ()
    allow_add_by_index: bool = False
    allow_remove: bool = False
    title: str | None = None
    instructions: tuple[str, ...] = ()
    resume_input: dict[str, Any] | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        interaction_type = str(self.type or "").strip().lower()
        if interaction_type not in INTERACTION_TYPES:
            raise ValueError(f"invalid interaction type: {self.type!r}")
        object.__setattr__(self, "id", _required_text(self.id, "interaction id"))
        object.__setattr__(self, "type", interaction_type)
        object.__setattr__(self, "prompt", _required_text(self.prompt, "interaction prompt"))
        object.__setattr__(
            self,
            "options",
            tuple(dict(item) for item in self.options),
        )
        object.__setattr__(
            self,
            "title",
            str(self.title).strip() if self.title is not None else None,
        )
        object.__setattr__(
            self,
            "instructions",
            tuple(str(item) for item in self.instructions),
        )
        object.__setattr__(
            self,
            "resume_input",
            dict(self.resume_input) if self.resume_input is not None else None,
        )
        object.__setattr__(self, "metadata", dict(self.metadata))

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "id": self.id,
            "type": self.type,
            "prompt": self.prompt,
            "options": [dict(item) for item in self.options],
            "allow_add_by_index": self.allow_add_by_index,
            "allow_remove": self.allow_remove,
        }
        if self.title:
            out["title"] = self.title
        if self.instructions:
            out["instructions"] = list(self.instructions)
        if self.resume_input is not None:
            out["resume_input"] = dict(self.resume_input)
        if self.metadata:
            out["metadata"] = dict(self.metadata)
        return out

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> InteractionRequest:
        if not isinstance(payload, dict):
            raise ValueError("interaction request must be an object")
        options = payload.get("options") or ()
        if not isinstance(options, (list, tuple)):
            raise ValueError("interaction options must be an array")
        if any(not isinstance(item, dict) for item in options):
            raise ValueError("interaction options must contain objects")
        resume_input = payload.get("resume_input")
        if resume_input is not None and not isinstance(resume_input, dict):
            raise ValueError("resume_input must be an object")
        metadata = payload.get("metadata") or {}
        if not isinstance(metadata, dict):
            raise ValueError("interaction metadata must be an object")
        return cls(
            id=payload.get("id", ""),
            type=payload.get("type", ""),
            prompt=payload.get("prompt", ""),
            options=tuple(options),
            allow_add_by_index=bool(payload.get("allow_add_by_index", False)),
            allow_remove=bool(payload.get("allow_remove", False)),
            title=payload.get("title"),
            instructions=tuple(payload.get("instructions") or ()),
            resume_input=resume_input,
            metadata=metadata,
        )


def manual_audio_render_task(
    *,
    task_id: str = "audio.render_master",
    title: str = "Render a master WAV manually",
    accepted_extensions: tuple[str, ...] = MANUAL_AUDIO_EXTENSIONS,
) -> InteractionRequest:
    """Describe a manual audio render without invoking FL Studio export APIs."""
    extensions = tuple(
        extension.lower() if extension.startswith(".") else f".{extension.lower()}"
        for extension in accepted_extensions
    )
    if not extensions:
        raise ValueError("manual audio task requires accepted file extensions")
    return InteractionRequest(
        id=task_id,
        type="manual_task",
        title=title,
        prompt=(
            "Render the audio manually in FL Studio, then provide the local file "
            "path to continue."
        ),
        instructions=(
            "Use FL Studio's export controls manually.",
            "Do not overwrite the current project or source audio.",
            "Return the path to the completed audio file.",
        ),
        resume_input={
            "type": "file_path",
            "accept": list(extensions),
        },
        metadata={
            "automatic_render": False,
            "source": "user_provided_file",
        },
    )

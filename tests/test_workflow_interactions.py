from __future__ import annotations

import pytest

from fls_pilot.analysis import AnalysisReport
from fls_pilot.runtime.interactions import (
    InteractionRequest,
    manual_audio_render_task,
)


def test_low_end_track_confirmation_interaction_round_trips() -> None:
    request = InteractionRequest(
        id="low_end.confirm_tracks",
        type="multi_select",
        prompt="Which tracks should be included in the low-end analysis?",
        options=(
            {"id": "mixer:2", "label": "Kick", "selected": True},
            {"id": "mixer:4", "label": "Bass", "selected": True},
        ),
        allow_add_by_index=True,
        allow_remove=True,
    )

    payload = request.to_dict()
    restored = InteractionRequest.from_dict(payload)

    assert payload["id"] == "low_end.confirm_tracks"
    assert payload["type"] == "multi_select"
    assert payload["allow_add_by_index"] is True
    assert payload["allow_remove"] is True
    assert restored == request


@pytest.mark.parametrize("interaction_type", ["single_select", "confirm", "manual_task"])
def test_supported_interaction_types_are_serializable(interaction_type: str) -> None:
    request = InteractionRequest(
        id=f"test.{interaction_type}",
        type=interaction_type,
        prompt="Review this request.",
    )

    assert InteractionRequest.from_dict(request.to_dict()) == request


def test_invalid_interaction_type_fails() -> None:
    with pytest.raises(ValueError, match="invalid interaction type"):
        InteractionRequest(id="unsafe", type="script", prompt="Run this.")


def test_analysis_report_serializes_interaction_request_payload() -> None:
    request = InteractionRequest(
        id="low_end.confirm_tracks",
        type="multi_select",
        prompt="Choose low-end tracks.",
        allow_add_by_index=True,
        allow_remove=True,
    )
    report = AnalysisReport(
        workflow="low_end_analysis",
        title="Low-End Analysis",
        analysis_mode="static_snapshot",
        interaction_requests=(request.to_dict(),),
    )

    restored = AnalysisReport.from_dict(report.to_dict())

    assert restored.interaction_requests == (request.to_dict(),)


def test_manual_audio_render_task_is_explicitly_manual() -> None:
    task = manual_audio_render_task()
    payload = task.to_dict()

    assert payload["type"] == "manual_task"
    assert payload["id"] == "audio.render_master"
    assert payload["title"] == "Render a master WAV manually"
    assert "manually" in payload["prompt"].lower()
    assert payload["resume_input"] == {
        "type": "file_path",
        "accept": [".wav", ".aiff", ".flac"],
    }
    assert payload["metadata"]["automatic_render"] is False

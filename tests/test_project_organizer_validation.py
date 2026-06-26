from __future__ import annotations

from fls_pilot import control_center


def test_project_organizer_marks_cleanup_heuristics_provisional() -> None:
    payload = control_center._build_project_organizer_report(
        channels=[
            {
                "channel": 1,
                "name": "Channel 1",
                "type": {"label": "genplug"},
                "target_mixer_track": 0,
                "target_name": "Master",
            }
        ],
        mixer_tracks=[{"i": 0, "name": "Master", "routes_to": []}],
        patterns=[],
        playlist_tracks=[],
        routing=[{"i": 0, "name": "Master", "routes_to": []}],
        template_context={},
    )
    report = control_center._generic_analysis_report_from_legacy(
        payload,
        "project_organizer",
        "Organizer",
    ).to_dict()

    unnamed = next(row for row in report["findings"] if row["id"] == "unnamed_channels")
    routing = next(row for row in report["findings"] if row["id"] == "routing_cleanup")

    assert payload["interaction_requests"][0]["id"] == "organizer.confirm_cleanup_heuristics"
    assert payload["cleanup_plan"]["blocked_until_human_validation"] is True
    assert payload["cleanup_plan"]["steps"][0]["blocked_until_human_validation"] is True
    assert unnamed["metadata"]["evidence_type"] == "name_based_detection"
    assert routing["metadata"]["evidence_type"] == "routing_based_detection"
    assert report["metadata"]["score_status"] == "provisional"
    assert report["metadata"]["blocked_fix_plan_until_confirmed"] is True


def test_project_organizer_user_decision_unblocks_cleanup_plan() -> None:
    payload = control_center._build_project_organizer_report(
        channels=[
            {
                "channel": 1,
                "name": "Channel 1",
                "type": {"label": "genplug"},
                "target_mixer_track": 0,
                "target_name": "Master",
            }
        ],
        mixer_tracks=[{"i": 0, "name": "Master", "routes_to": []}],
        patterns=[],
        playlist_tracks=[],
        routing=[{"i": 0, "name": "Master", "routes_to": []}],
        template_context={},
        user_decisions=(
            {
                "interaction_id": "organizer.confirm_cleanup_heuristics",
                "decision": "selected",
                "selected": ["routing_cleanup"],
            },
        ),
    )
    report = control_center._generic_analysis_report_from_legacy(
        payload,
        "project_organizer",
        "Organizer",
    ).to_dict()

    routing = next(row for row in report["findings"] if row["id"] == "routing_cleanup")

    assert payload["cleanup_plan"]["blocked_until_human_validation"] is False
    assert payload["user_decisions"][0]["interaction_id"] == (
        "organizer.confirm_cleanup_heuristics"
    )
    assert routing["severity"] == "info"
    assert routing["metadata"]["human_validation_required"] is False
    assert routing["metadata"]["validated_by_user"] is True
    assert routing["metadata"]["user_intent"] == "intentional"
    assert report["metadata"]["score_status"] == "final"
    assert report["metadata"]["blocked_fix_plan_until_confirmed"] is False

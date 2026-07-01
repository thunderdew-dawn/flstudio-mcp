from __future__ import annotations

from fls_pilot import control_center
from fls_pilot.analysis import audio_features_placeholder


def test_audio_features_placeholder_allows_null_values() -> None:
    payload = audio_features_placeholder(source_kind="rendered_master")

    assert payload["contract_version"] == "fls-pilot.audio-features.v1"
    assert payload["status"] == "pending_external_analyzer"
    assert all(value is None for value in payload["features"].values())


def test_level_3_report_lists_expected_checks_without_audio_findings() -> None:
    report = control_center._build_mix_review_report(
        {
            "playing": False,
            "levels_valid": False,
            "peak_window": {"source": "none"},
            "tracks": [{"index": 0, "name": "Master", "plugins": [], "routes_to": []}],
            "template_context": {},
            "gather_errors": [],
        },
        options={"level": 3},
    )

    assert report["mix_review"]["evidence_summary"]["rendered_master"] == "missing"
    assert "Integrated LUFS" in report["mix_review"]["expected_checks"]
    assert not any(row["rule"].startswith("rendered") for row in report["findings"])
    assert report["metadata"]["external_audio_analyzer"]["status"] == "not_merged_yet"

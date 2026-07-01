from __future__ import annotations

from fls_pilot import control_center


def test_level_4_report_lists_stem_roles_without_fake_stem_analysis() -> None:
    report = control_center._build_mix_review_report(
        {
            "playing": False,
            "levels_valid": False,
            "peak_window": {"source": "none"},
            "tracks": [{"index": 0, "name": "Master", "plugins": [], "routes_to": []}],
            "template_context": {},
            "gather_errors": [],
        },
        options={
            "level": 4,
            "audio_evidence": [
                {
                    "source_kind": "rendered_stem",
                    "stem_role": "kick",
                    "path": "/tmp/kick.wav",
                    "status": "pending_external_analyzer",
                }
            ],
        },
    )

    stem_request = report["mix_review"]["audio_evidence_requests"]["rendered_stems"][0]
    assert stem_request["stem_role"] == "kick"
    assert "Kick/Bass Masking" in report["mix_review"]["expected_checks"]
    assert "Low-End Phase" in report["mix_review"]["expected_checks"]
    assert report["mix_review"]["evidence_summary"]["rendered_stems"] == "missing"
    assert report["mix_review"]["external_audio_analyzer"]["status"] == "not_merged_yet"
    assert not any("masking" in row["rule"].lower() for row in report["findings"])
    assert not any("phase" in row["rule"].lower() for row in report["findings"])


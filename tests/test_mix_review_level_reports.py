from __future__ import annotations

from fls_pilot import control_center


def _track(index, name, *, peak_db=None, peak_max=None, plugins=None):
    return {
        "index": index,
        "name": name,
        "vol_db": 0.0,
        "peak_db": peak_db,
        "peak_max": peak_max,
        "pan": 0.0,
        "stereo_sep": 0.0,
        "plugins": plugins or [],
        "routes_to": [{"dst": 0}] if index else [],
    }


def test_default_mix_review_report_has_level_1_metadata() -> None:
    report = control_center._build_mix_review_report(
        {
            "playing": False,
            "levels_valid": False,
            "peak_window": {"source": "none"},
            "tracks": [_track(0, "Master"), _track(1, "Pad", plugins=[])],
            "template_context": {},
            "gather_errors": [],
        }
    )

    assert report["summary"]["mix_review_level"] == 1
    assert report["mix_review"]["evidence_summary"]["static_snapshot"] == "available"
    assert report["metadata"]["external_audio_analyzer"]["status"] == "not_merged_yet"


def test_level_2_report_has_capture_metadata() -> None:
    report = control_center._build_mix_review_report(
        {
            "playing": False,
            "levels_valid": False,
            "peak_window": {"source": "none"},
            "tracks": [_track(0, "Master")],
            "template_context": {},
            "gather_errors": [],
        },
        options={
            "level": 2,
            "loop_seconds": 12,
            "playback_mode": "user_starts",
            "marker_name": "Drop",
        },
    )

    assert report["summary"]["mix_review_level"] == 2
    assert report["mix_review"]["capture"]["loop_seconds"] == 12
    assert report["mix_review"]["evidence_summary"]["watch_window"] == "missing"
    assert report["next_actions"][0]["action"] == "start_watch"


def test_level_1_without_peaks_skips_peak_findings() -> None:
    report = control_center._build_mix_review_report(
        {
            "playing": False,
            "levels_valid": False,
            "peak_window": {"source": "none"},
            "tracks": [_track(0, "Master"), _track(1, "Lead", plugins=[])],
            "template_context": {},
            "gather_errors": [],
        },
        options={"level": 1},
    )

    rules = {row["rule"] for row in report["findings"]}
    assert "clipping" not in rules
    assert "headroom" not in rules


def test_level_2_with_watch_evidence_enables_peak_findings() -> None:
    report = control_center._build_mix_review_report(
        {
            "playing": False,
            "levels_valid": True,
            "peak_window": {"source": "watch"},
            "live_window": {"freshness": "fresh", "limitations": []},
            "tracks": [
                _track(0, "Master", peak_db=0.1, peak_max=1.01),
                _track(1, "Lead", peak_db=-0.2, peak_max=0.98),
            ],
            "template_context": {},
            "gather_errors": [],
        },
        options={"level": 2},
    )

    rules = {row["rule"] for row in report["findings"]}
    clipping = next(row for row in report["findings"] if row["rule"] == "clipping")
    assert "clipping" in rules
    assert report["mix_review"]["evidence_summary"]["watch_window"] == "available"
    assert clipping["evidence_type"] == "watch_window"
    assert clipping["proof_status"] == "evidence_backed"


def test_heuristic_findings_are_low_confidence() -> None:
    report = control_center._build_mix_review_report(
        {
            "playing": False,
            "levels_valid": False,
            "peak_window": {"source": "none"},
            "tracks": [_track(0, "Master"), _track(1, "Lead Vox", plugins=[])],
            "template_context": {},
            "gather_errors": [],
        },
        options={"level": 1},
    )

    hpf = next(row for row in report["findings"] if row["rule"] == "missing_hpf")
    assert hpf["proof_status"] == "heuristic"
    assert hpf["confidence"] == "low"
    assert hpf["requires_audio_evidence_for_confirmation"] is True

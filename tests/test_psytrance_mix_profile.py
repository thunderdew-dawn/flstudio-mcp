from __future__ import annotations

import json
from pathlib import Path


def test_psytrance_mix_review_profile_is_conservative() -> None:
    profile_path = (
        Path(__file__).resolve().parents[1]
        / "src"
        / "fls_pilot"
        / "packs"
        / "psytrance"
        / "mix_review_profile.json"
    )
    payload = json.loads(profile_path.read_text(encoding="utf-8"))

    assert payload["profile_id"] == "psytrance"
    assert payload["evidence_policy"]["static_profile_claims_audio_facts"] is False
    assert payload["profile_mode"] == "heuristic_guidance"
    assert "kick_bass_relationship" in payload["focus_areas"]
    assert "no static psytrance finding is treated as audio-confirmed" in " ".join(
        payload["limitations"]
    )

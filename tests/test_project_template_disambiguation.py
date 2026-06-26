from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fls_pilot import project_templates as templates

ROOT = Path(__file__).resolve().parents[1]
PROFILE_DIR = ROOT / "knowledgebase" / "templates" / "profiles"


def _profile(slug: str) -> dict[str, Any]:
    return json.loads((PROFILE_DIR / f"{slug}.json").read_text())


def _routes(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for row in rows:
        if row.get("index") is None:
            continue
        out.append(
            {
                "i": row["index"],
                "name": row.get("name"),
                "routes_to": [
                    {"dst": route.get("target"), "level": route.get("level")}
                    for route in row.get("routes_to", [])
                ],
            }
        )
    return out


def _live_rows(slug: str, *, source_names: dict[int, str] | None = None) -> list[dict[str, Any]]:
    profile = _profile(slug)
    rows = [dict(row) for row in profile["mixer_tracks"]]
    for row in rows:
        if source_names and row.get("index") in source_names:
            row["name"] = source_names[row["index"]]
    for reserved_range in profile.get("reserved_ranges", []):
        start = int(reserved_range["from"])
        needed = int(profile["template_detection"]["reserved_placeholder_min_count"])
        for index in range(start, start + needed):
            rows.append(
                {
                    "index": index,
                    "name": f"Insert {index}",
                    "routes_to": [
                        {"target": target, "level": reserved_range.get("route_level")}
                        for target in reserved_range.get("default_routes_to", [])
                    ],
                }
            )
    return rows


def _channels(slug: str) -> list[dict[str, Any]]:
    return [
        {
            "channel": row["channel_index"],
            "name": row["channel_name"],
            "target_mixer_track": row["target_mixer_track"],
            "target_name": row.get("target_name"),
            "type": {"label": row.get("type")},
        }
        for row in _profile(slug).get("channel_routes", [])
    ]


def test_edm_house_profile_wins_with_edm_channel_routes() -> None:
    rows = _live_rows("edm_house")
    context = templates.classify_topology(rows, _routes(rows), _channels("edm_house"))

    assert context["matched"] is True
    assert context["ambiguous"] is False
    assert context["template_slug"] == "edm_house"
    assert context["evidence"]["channel_matches"] >= 10


def test_specific_channel_routes_beat_generic_profile_overlap() -> None:
    rows = _live_rows("dubstep")
    context = templates.classify_topology(rows, _routes(rows), _channels("dubstep"))

    assert context["matched"] is True
    assert context["ambiguous"] is False
    assert context["template_slug"] == "dubstep"
    assert context["candidate_slugs"] == ["dubstep"]


def test_edm_house_generic_names_do_not_select_trap_profiles() -> None:
    generic_trap_names = {
        4: "Kick 1",
        5: "Kick 2",
        6: "Snare 1",
        7: "Hi-Hats",
        8: "Cymbals",
        9: "Sub 1",
        10: "Bass 1",
        11: "Bass 2",
    }
    rows = _live_rows("edm_house", source_names=generic_trap_names)
    context = templates.classify_topology(rows, _routes(rows), _channels("edm_house"))

    assert context["template_slug"] != "hiphop_trap"
    assert context["template_slug"] != "trap"
    assert context["matched"] is False or context["ambiguous"] is True


def test_trap_and_hiphop_exact_topology_is_ambiguous_and_suppresses_nothing() -> None:
    rows = _live_rows("trap")
    context = templates.classify_topology(rows, _routes(rows), _channels("trap"))

    assert context["matched"] is True
    assert context["ambiguous"] is True
    assert {"hiphop_trap", "trap"}.issubset(set(context["candidate_slugs"]))
    assert templates.compact_context(context)["ambiguity_reason"] == "profile_scores_tied"
    assert templates.suppresses(context, 22, "suppress_unused_track") is False
    assert templates.is_reserved_placeholder(context, 22) is False
    assert templates.is_template_bus(context, 117) is False
    assert templates.compact_context(context)["ambiguous"] is True


def test_user_decision_resolves_ambiguous_template_profile() -> None:
    rows = _live_rows("trap")
    context = templates.classify_topology(rows, _routes(rows), _channels("trap"))

    resolved = templates.resolve_with_user_decisions(
        context,
        [
            {
                "interaction_id": "template.confirm_profile",
                "decision": "selected",
                "selected": ["trap"],
            }
        ],
        mixer_tracks=rows,
        routing_rows=_routes(rows),
        channel_rows=_channels("trap"),
    )

    compact = templates.compact_context(resolved)
    assert resolved["ambiguous"] is False
    assert resolved["template_slug"] == "trap"
    assert resolved["resolved_by_user"] is True
    assert resolved["validated_by_user"] is True
    assert compact["selected_template_slug"] == "trap"
    assert compact["validated_by_user"] is True
    assert templates.suppresses(resolved, 24, "suppress_unused_track") is True
    assert templates.is_reserved_placeholder(resolved, 24) is True


def test_user_decision_none_keeps_template_suppressions_disabled() -> None:
    rows = _live_rows("trap")
    context = templates.classify_topology(rows, _routes(rows), _channels("trap"))

    resolved = templates.resolve_with_user_decisions(
        context,
        [
            {
                "interaction_id": "template.confirm_profile",
                "decision": "selected",
                "selected": ["none"],
            }
        ],
        mixer_tracks=rows,
        routing_rows=_routes(rows),
        channel_rows=_channels("trap"),
    )

    compact = templates.compact_context(resolved)
    assert resolved["matched"] is False
    assert resolved["selected_template_slug"] == "none"
    assert compact["resolved_by_user"] is True
    assert compact["selected_template_slug"] == "none"
    assert templates.suppresses(resolved, 24, "suppress_unused_track") is False
    assert templates.is_reserved_placeholder(resolved, 24) is False

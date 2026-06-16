from __future__ import annotations

from fls_pilot.analysis import (
    CanonicalEntity,
    channel_entity_id,
    mixer_count_policy,
    mixer_entity_id,
    pattern_count_policy,
    pattern_entity_id,
    playlist_count_policy,
    playlist_slot_entity_id,
    plugin_entity_id,
)


def test_canonical_entity_ids_are_stable() -> None:
    assert mixer_entity_id(0) == "mixer:master"
    assert mixer_entity_id("master") == "mixer:master"
    assert mixer_entity_id("current") == "mixer:current"
    assert mixer_entity_id(12) == "mixer:12"
    assert channel_entity_id(10) == "channel:10"
    assert pattern_entity_id(1) == "pattern:1"
    assert playlist_slot_entity_id(120) == "playlist:slot:120"
    assert plugin_entity_id(mixer_track=12, slot=3) == "plugin:mixer:12:slot:3"
    assert plugin_entity_id(mixer_track="master", slot=8) == "plugin:mixer:master:slot:8"


def test_canonical_entity_to_dict_uses_label_as_metadata_not_identity() -> None:
    entity = CanonicalEntity(
        type="mixer_track",
        canonical_id="mixer:4",
        index=4,
        display_name="Bass Bus",
    )

    assert entity.to_dict() == {
        "type": "mixer_track",
        "canonical_id": "mixer:4",
        "index": 4,
        "display_name": "Bass Bus",
    }


def test_pattern_count_policy_preserves_ui_minimum_pattern() -> None:
    zero = pattern_count_policy(0)
    many = pattern_count_policy(3)

    assert zero["api_count"] == 0
    assert zero["display_count"] == 1
    assert zero["display_count_policy"] == "minimum_one_pattern"
    assert zero["notes"]
    assert many["api_count"] == 3
    assert many["display_count"] == 3


def test_playlist_count_policy_separates_slots_from_used_tracks() -> None:
    policy = playlist_count_policy(used_tracks=12)

    assert policy["slot_count"] == 500
    assert policy["used_tracks"] == 12
    assert policy["display_mode"] == "fixed_slots"


def test_mixer_count_policy_tracks_special_rows_separately() -> None:
    policy = mixer_count_policy(api_slots=127)

    assert policy["api_slots"] == 127
    assert policy["user_track_count"] == 126
    assert policy["special_tracks"] == ["current", "master"]
    assert policy["display_count_policy"] == "exclude_current_and_master"

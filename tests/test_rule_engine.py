from __future__ import annotations

import pytest

from fls_pilot.rules import (
    RuleCondition,
    RuleDefinition,
    evaluate_condition,
    evaluate_rules,
)


@pytest.mark.parametrize(
    ("condition", "observation"),
    [
        (RuleCondition("name", "eq", "Bass"), {"name": "Bass"}),
        (RuleCondition("name", "ne", "Kick"), {"name": "Bass"}),
        (RuleCondition("roles", "contains", "bass"), {"roles": ["bass", "sub"]}),
        (RuleCondition("role", "in", ["kick", "bass"]), {"role": "bass"}),
        (RuleCondition("peak_db", "gte", -6.0), {"peak_db": -3.0}),
        (RuleCondition("peak_db", "lte", -6.0), {"peak_db": -9.0}),
        (RuleCondition("active", "truthy"), {"active": 1}),
        (RuleCondition("muted", "falsy"), {"muted": False}),
    ],
)
def test_rule_engine_supports_declared_operators(
    condition: RuleCondition,
    observation: dict,
) -> None:
    assert evaluate_condition(observation, condition) is True


def test_rule_engine_evaluates_nested_fields_and_returns_structured_finding() -> None:
    rule = RuleDefinition(
        id="low_end.wide_bass",
        title="Bass track uses stereo width",
        severity="medium",
        risk_score=45,
        confidence_score=70,
        evidence_mode="static_snapshot",
        conditions=(
            RuleCondition("track.role", "eq", "bass"),
            RuleCondition("track.stereo_separation", "gte", 0.25),
        ),
        metadata={"profile": "default"},
    )

    findings = evaluate_rules(
        {"track": {"role": "bass", "stereo_separation": 0.5}},
        (rule,),
    )

    assert len(findings) == 1
    data = findings[0].to_dict()
    assert data["rule_id"] == "low_end.wide_bass"
    assert data["risk_score"] == 45
    assert data["evidence"][1]["actual"] == 0.5
    assert data["metadata"]["profile"] == "default"


def test_missing_or_incompatible_fields_evaluate_false() -> None:
    assert evaluate_condition({}, RuleCondition("missing", "eq", 1)) is False
    assert evaluate_condition(
        {"value": "not-a-number"},
        RuleCondition("value", "gte", 1),
    ) is False


def test_invalid_operator_is_rejected_without_expression_evaluation() -> None:
    with pytest.raises(ValueError, match="invalid rule operator"):
        RuleCondition("value", "__import__", "os")


def test_any_match_mode_is_deterministic() -> None:
    rule = RuleDefinition(
        id="role.low_end",
        title="Low-end role",
        severity="info",
        risk_score=5,
        confidence_score=50,
        evidence_mode="static_snapshot",
        conditions=(
            RuleCondition("role", "eq", "kick"),
            RuleCondition("role", "eq", "bass"),
        ),
        match="any",
    )

    assert len(evaluate_rules({"role": "bass"}, (rule,))) == 1
    assert evaluate_rules({"role": "lead"}, (rule,)) == ()

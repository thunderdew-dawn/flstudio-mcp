from __future__ import annotations

import pytest

from fls_pilot.workflow_identity import (
    canonical_workflow_id,
    is_builtin_workflow_id,
    is_custom_workflow_id,
    normalize_workflow_id,
)

def test_canonical_workflow_id_preserves_builtins() -> None:
    assert canonical_workflow_id("low-end") == "low_end_analysis"
    assert canonical_workflow_id("low_end_analysis") == "low_end_analysis"
    assert canonical_workflow_id("mix_review") == "mix_review"

def test_canonical_workflow_id_rejects_unknowns_and_customs() -> None:
    with pytest.raises(ValueError, match="unknown workflow id"):
        canonical_workflow_id("unknown_workflow")
    
    with pytest.raises(ValueError, match="unknown workflow id"):
        canonical_workflow_id("user.low_end_level4")

def test_normalize_workflow_id_without_allow_custom_acts_like_canonical() -> None:
    assert normalize_workflow_id("low-end") == "low_end_analysis"
    with pytest.raises(ValueError, match="invalid or unknown workflow id"):
        normalize_workflow_id("user.low_end_level4")

def test_normalize_workflow_id_with_allow_custom() -> None:
    # Builtins still work
    assert normalize_workflow_id("low-end", allow_custom=True) == "low_end_analysis"
    assert normalize_workflow_id("low_end_analysis", allow_custom=True) == "low_end_analysis"
    
    # Valid customs work
    assert normalize_workflow_id("user.low_end_level4", allow_custom=True) == "user.low_end_level4"
    assert normalize_workflow_id("local.mastering_preflight", allow_custom=True) == "local.mastering_preflight"
    
    # Invalid customs reject
    with pytest.raises(ValueError, match="invalid or unknown workflow id"):
        normalize_workflow_id("builtin.low_end_analysis", allow_custom=True)
    with pytest.raises(ValueError, match="invalid or unknown workflow id"):
        normalize_workflow_id("user.bad/id", allow_custom=True)
    with pytest.raises(ValueError, match="invalid or unknown workflow id"):
        normalize_workflow_id("user. space", allow_custom=True)
    with pytest.raises(ValueError, match="invalid or unknown workflow id"):
        normalize_workflow_id("unknown", allow_custom=True)

def test_is_builtin_workflow_id() -> None:
    assert is_builtin_workflow_id("low-end") is True
    assert is_builtin_workflow_id("low_end_analysis") is True
    assert is_builtin_workflow_id("user.low_end_level4") is False

def test_is_custom_workflow_id() -> None:
    assert is_custom_workflow_id("user.low_end_level4") is True
    assert is_custom_workflow_id("local.mastering_preflight") is True
    assert is_custom_workflow_id("builtin.low_end_analysis") is False
    assert is_custom_workflow_id("low-end") is False
    assert is_custom_workflow_id("user. space") is False
    assert is_custom_workflow_id("") is False

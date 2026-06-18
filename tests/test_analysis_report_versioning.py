from __future__ import annotations

import pytest

from fls_pilot.analysis import (
    ANALYSIS_REPORT_CONTRACT_VERSION,
    AnalysisReport,
    IncompatibleReportVersionError,
)


def _report_payload() -> dict:
    return AnalysisReport(
        workflow="mix_review",
        title="Mix Review",
        analysis_mode="static_snapshot",
    ).to_dict()


def test_analysis_report_v1_is_accepted() -> None:
    restored = AnalysisReport.from_dict(_report_payload())
    assert restored.workflow == "mix_review"


@pytest.mark.parametrize(
    "version",
    [None, "", "fls-pilot.workflow-report.v1", "fls-pilot.analysis-report.v2"],
)
def test_missing_legacy_and_unknown_versions_are_rejected(version: str | None) -> None:
    payload = _report_payload()
    if version is None:
        payload.pop("contract_version")
    else:
        payload["contract_version"] = version

    with pytest.raises(IncompatibleReportVersionError) as exc_info:
        AnalysisReport.from_dict(payload)

    assert exc_info.value.code == "incompatible_report_version"
    assert ANALYSIS_REPORT_CONTRACT_VERSION in str(exc_info.value)

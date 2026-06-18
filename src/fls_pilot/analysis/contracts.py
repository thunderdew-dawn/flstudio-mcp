"""Version gates for public analysis contracts."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

ANALYSIS_REPORT_CONTRACT_VERSION = "fls-pilot.analysis-report.v1"
ACCEPTED_ANALYSIS_REPORT_VERSIONS = frozenset({ANALYSIS_REPORT_CONTRACT_VERSION})


class IncompatibleReportVersionError(ValueError):
    """Raised when a report does not use the exclusive public contract."""

    code = "incompatible_report_version"

    def __init__(self, received: Any) -> None:
        self.received = received
        expected = ANALYSIS_REPORT_CONTRACT_VERSION
        if received is None:
            detail = "missing contract_version"
        else:
            detail = f"unsupported contract_version: {received!r}"
        super().__init__(f"{detail}; expected {expected!r}")


def require_analysis_report_version(payload: Mapping[str, Any]) -> str:
    """Return the accepted version or reject the payload."""
    version = payload.get("contract_version")
    if not isinstance(version, str) or version not in ACCEPTED_ANALYSIS_REPORT_VERSIONS:
        raise IncompatibleReportVersionError(version)
    return version

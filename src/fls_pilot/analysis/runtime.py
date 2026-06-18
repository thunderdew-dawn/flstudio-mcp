"""Compatibility accessors backed by canonical Runtime services."""

from __future__ import annotations

from ..runtime.access import RuntimeAnalysisBroker, RuntimeReportStore

_BROKER = RuntimeAnalysisBroker()
_REPORT_STORE = RuntimeReportStore()


def get_analysis_broker() -> RuntimeAnalysisBroker:
    return _BROKER


def get_report_store() -> RuntimeReportStore:
    return _REPORT_STORE

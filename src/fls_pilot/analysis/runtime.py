"""Process-local analysis broker and report-store ownership."""

from __future__ import annotations

from .broker import AnalysisBroker
from .store import ReportStore

_BROKER = AnalysisBroker()
_REPORT_STORE = ReportStore()


def get_analysis_broker() -> AnalysisBroker:
    return _BROKER


def get_report_store() -> ReportStore:
    return _REPORT_STORE

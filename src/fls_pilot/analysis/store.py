"""In-memory store for recent analysis workflow reports."""

from __future__ import annotations

import collections
import threading
from typing import Any, Optional

from .schema import AnalysisReport


class ReportStore:
    """Thread-safe, session-local store for analysis reports."""

    def __init__(self, limit_per_workflow: int = 5) -> None:
        self._limit = limit_per_workflow
        self._reports: dict[str, collections.deque[AnalysisReport]] = collections.defaultdict(
            lambda: collections.deque(maxlen=self._limit)
        )
        self._lock = threading.RLock()

    def add_report(self, report: AnalysisReport) -> None:
        """Store a new report."""
        with self._lock:
            self._reports[report.workflow].append(report)

    def get_latest_report(self, workflow: str) -> Optional[AnalysisReport]:
        """Get the most recent report for a given workflow."""
        with self._lock:
            queue = self._reports.get(workflow)
            if not queue:
                return None
            return queue[-1]

    def clear(self) -> None:
        """Clear all stored reports."""
        with self._lock:
            self._reports.clear()

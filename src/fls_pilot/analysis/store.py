"""In-memory store for recent analysis workflow reports."""

from __future__ import annotations

import collections
import threading
from collections.abc import Iterable

from .schema import AnalysisReport
from ..runtime.contracts import ProjectContext


class ReportStore:
    """Thread-safe, session-local store for analysis reports."""

    def __init__(self, limit_per_workflow: int = 5) -> None:
        self._limit = limit_per_workflow
        self._reports: dict[str, collections.deque[AnalysisReport]] = collections.defaultdict(
            lambda: collections.deque(maxlen=self._limit)
        )
        self._lock = threading.RLock()

    def add_report(self, report: AnalysisReport) -> AnalysisReport:
        """Store a new report."""
        with self._lock:
            self._reports[report.workflow].append(report)
        return report

    def get_latest_report(self, workflow: str) -> AnalysisReport | None:
        """Get the most recent report for a given workflow."""
        with self._lock:
            queue = self._reports.get(workflow)
            if not queue:
                return None
            return queue[-1]

    def list_reports(self, workflow: str | None = None) -> tuple[AnalysisReport, ...]:
        """Return reports in insertion order for diagnostics and Runtime transport."""
        with self._lock:
            if workflow is not None:
                return tuple(self._reports.get(workflow, ()))
            rows: list[AnalysisReport] = []
            for queue in self._reports.values():
                rows.extend(queue)
            return tuple(sorted(rows, key=lambda report: report.created_at))

    def get_latest_compatible(
        self,
        workflow: str,
        context: ProjectContext,
        *,
        allow_legacy_fingerprint: bool = True,
    ) -> AnalysisReport | None:
        """Return the newest report that belongs to the current Runtime project."""
        with self._lock:
            candidates = reversed(tuple(self._reports.get(workflow, ())))
            for report in candidates:
                if _report_matches_context(
                    report,
                    context,
                    allow_legacy_fingerprint=allow_legacy_fingerprint,
                ):
                    return report
        return None

    def invalidate(
        self,
        *,
        workflows: Iterable[str] | None = None,
        project_scope_id: str | None = None,
    ) -> int:
        """Remove affected reports; retained unrelated project scopes stay intact."""
        selected = set(workflows or ())
        removed = 0
        with self._lock:
            for workflow in tuple(self._reports):
                if selected and workflow not in selected:
                    continue
                queue = self._reports[workflow]
                kept = collections.deque(maxlen=self._limit)
                for report in queue:
                    in_scope = (
                        project_scope_id is None
                        or report.project_scope_id == project_scope_id
                    )
                    if in_scope:
                        removed += 1
                    else:
                        kept.append(report)
                if kept:
                    self._reports[workflow] = kept
                else:
                    self._reports.pop(workflow, None)
        return removed

    def clear(self) -> None:
        """Clear all stored reports."""
        with self._lock:
            self._reports.clear()


def _report_matches_context(
    report: AnalysisReport,
    context: ProjectContext,
    *,
    allow_legacy_fingerprint: bool,
) -> bool:
    if not context.is_known:
        return False
    if report.runtime_session_id and report.runtime_session_id != context.runtime_session_id:
        return False
    if report.project_scope_id:
        return report.project_scope_id == context.project_scope_id
    if allow_legacy_fingerprint and report.project_fingerprint:
        return report.project_fingerprint == context.project_fingerprint
    return False

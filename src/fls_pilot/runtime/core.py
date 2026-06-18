"""Canonical in-process Runtime ownership and orchestration."""

from __future__ import annotations

import threading
from typing import Any

from .. import __version__
from ..analysis.broker import AnalysisBroker, StaticProjectSnapshot, StaticSnapshotPolicy
from ..analysis.health_aggregator import aggregate_project_health
from ..analysis.observations import ObservationStore
from ..analysis.schema import AnalysisReport
from ..analysis.store import ReportStore
from ..workflows.registry import DEFAULT_WORKFLOW_REGISTRY, WorkflowRegistry
from ..workflows.registry import canonical_workflow_id
from .contracts import ProjectContext, RuntimeSession
from .project_context import ProjectContextService


class RuntimeCore:
    """Own canonical project evidence and reports for one daemon lifetime."""

    def __init__(
        self,
        *,
        session: RuntimeSession | None = None,
        observation_store: ObservationStore | None = None,
        report_store: ReportStore | None = None,
        workflow_registry: WorkflowRegistry = DEFAULT_WORKFLOW_REGISTRY,
    ) -> None:
        self.session = session or RuntimeSession(runtime_version=__version__)
        self.observation_store = observation_store or ObservationStore()
        self.analysis_broker = AnalysisBroker(
            observation_store=self.observation_store,
            source="runtime",
        )
        self.report_store = report_store or ReportStore()
        self.workflow_registry = workflow_registry
        self.project_contexts = ProjectContextService(self.session)
        self._lock = threading.RLock()

    @property
    def project_context(self) -> ProjectContext:
        return self.project_contexts.current

    def get_static_project_snapshot(
        self,
        bridge: Any,
        policy: StaticSnapshotPolicy | None = None,
    ) -> StaticProjectSnapshot:
        with self._lock:
            snapshot = self.analysis_broker.get_static_project_snapshot(bridge, policy)
            self.project_contexts.update(snapshot)
            return snapshot

    def add_report(self, report: AnalysisReport) -> AnalysisReport:
        with self._lock:
            context = self.project_context
            try:
                workflow_id = canonical_workflow_id(report.workflow)
            except ValueError:
                workflow_id = report.workflow
            scoped = AnalysisReport(
                **{
                    **report.__dict__,
                    "workflow": workflow_id,
                    "runtime_session_id": context.runtime_session_id,
                    "project_scope_id": context.project_scope_id,
                    "project_fingerprint": (
                        report.project_fingerprint or context.project_fingerprint
                    ),
                    "snapshot_id": report.snapshot_id or context.snapshot_id,
                    "snapshot_revision": (
                        report.snapshot_revision or context.snapshot_revision
                    ),
                }
            )
            self.report_store.add_report(scoped)
            return scoped

    def latest_report(self, workflow_id: str) -> AnalysisReport | None:
        return self.report_store.get_latest_compatible(
            workflow_id,
            self.project_context,
        )

    def project_health(self) -> dict[str, Any]:
        return aggregate_project_health(
            self.report_store,
            project_context=self.project_context,
        )

    def invalidate(
        self,
        event: str,
        *,
        workflows: tuple[str, ...] = (),
    ) -> dict[str, int]:
        with self._lock:
            observations = self.observation_store.invalidate(
                event=event,
                reason=event,
            )
            reports = self.report_store.invalidate(
                workflows=workflows or None,
                project_scope_id=self.project_context.project_scope_id,
            )
            self.project_contexts.invalidate(event)
            return {"observations": observations, "reports": reports}

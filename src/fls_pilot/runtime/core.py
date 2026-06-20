"""Canonical in-process Runtime ownership and orchestration."""

from __future__ import annotations

import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .. import __version__
from ..analysis.broker import AnalysisBroker, StaticProjectSnapshot, StaticSnapshotPolicy
from ..analysis.evidence_links import EvidenceLinkStore
from ..analysis.health_aggregator import aggregate_project_health
from ..analysis.observations import ObservationStore
from ..analysis.schema import AnalysisReport
from ..analysis.store import ReportStore
from ..workflows.registry import DEFAULT_WORKFLOW_REGISTRY, WorkflowRegistry, canonical_workflow_id
from .artifacts import AudioArtifactStore
from .contracts import ProjectContext, RuntimeSession
from .job_store import JobStore
from .jobs import JobHandler, RuntimeJobQueue
from .project_context import ProjectContextService
from .workflow_store import WorkflowStore
from .effective_workflows import EffectiveWorkflowRegistry
from .workflow_run_store import WorkflowRunStore


class RuntimeCore:
    """Own canonical project evidence and reports for one daemon lifetime."""

    def __init__(
        self,
        *,
        session: RuntimeSession | None = None,
        observation_store: ObservationStore | None = None,
        report_store: ReportStore | None = None,
        workflow_registry: WorkflowRegistry = DEFAULT_WORKFLOW_REGISTRY,
        workflow_store_path: str | Path | None = None,
        job_store_path: str | Path | None = None,
        job_worker_concurrency: int = 1,
        job_result_validator: Callable[[dict[str, Any]], bool] | None = None,
        artifact_store: AudioArtifactStore | None = None,
        evidence_link_store: EvidenceLinkStore | None = None,
        workflow_run_store_path: str | Path | None = None,
    ) -> None:
        self.session = session or RuntimeSession(runtime_version=__version__)
        self.observation_store = observation_store or ObservationStore()
        self.analysis_broker = AnalysisBroker(
            observation_store=self.observation_store,
            source="runtime",
        )
        self.report_store = report_store or ReportStore()
        self.workflow_registry = workflow_registry
        self.workflow_store = WorkflowStore(workflow_store_path)
        self.effective_workflows = EffectiveWorkflowRegistry(self.workflow_registry, self.workflow_store)
        self.project_contexts = ProjectContextService(self.session)
        self.audio_artifacts = artifact_store or AudioArtifactStore()
        self.evidence_links = evidence_link_store or EvidenceLinkStore()
        self.workflow_run_store = WorkflowRunStore(workflow_run_store_path)
        self.job_store = JobStore(job_store_path)
        self.jobs = RuntimeJobQueue(
            self.job_store,
            max_workers=job_worker_concurrency,
            result_validator=(
                job_result_validator or self.audio_artifacts.validate_result_ref
            ),
        )
        self._lock = threading.RLock()

    def register_job_handler(self, kind: str, handler: JobHandler) -> None:
        self.jobs.register_handler(kind, handler)

    def close(self, *, wait: bool = True) -> None:
        self.jobs.close(wait=wait)

    def attach_audio_artifact(
        self,
        artifact_id: str,
        *,
        evidence_kind: str,
        stem_role: str | None = None,
        workflow_targets: tuple[str, ...] = (),
        confirmed_by_user: bool = False,
    ):
        return self.analysis_broker.record_rendered_audio_features(
            artifact_store=self.audio_artifacts,
            evidence_links=self.evidence_links,
            artifact_id=artifact_id,
            project_context=self.project_context,
            evidence_kind=evidence_kind,
            stem_role=stem_role,
            workflow_targets=workflow_targets,
            confirmed_by_user=confirmed_by_user,
        )

    def rendered_audio_observations(
        self,
        *,
        workflow_target: str | None = None,
    ):
        compatible_links = {
            link.link_id: link
            for link in self.evidence_links.list(
                context=self.project_context,
                workflow_target=workflow_target,
            )
        }
        rows = []
        for observation in self.observation_store.list(
            kind="rendered_audio_features",
            include_stale=False,
        ):
            payload = observation.payload if isinstance(observation.payload, dict) else {}
            link = compatible_links.get(str(payload.get("evidence_link_id") or ""))
            if link is None:
                continue
            if not self.audio_artifacts.validate_result_ref(
                {"kind": "audio_features", "artifact_id": link.artifact_id}
            ):
                continue
            rows.append(observation)
        return tuple(rows)

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
            observations=self.rendered_audio_observations(),
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

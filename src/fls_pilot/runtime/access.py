"""Compatibility accessors that delegate canonical state to Runtime services."""

from __future__ import annotations

import os
from typing import Any

from ..analysis.broker import StaticProjectSnapshot, StaticSnapshotPolicy
from ..analysis.live import LiveMeterPolicy, LiveMeterWindow
from ..analysis.schema import AnalysisReport
from ..connection import TCPBridge
from .client import RuntimeClient, RuntimeClientError

_LOCAL_RUNTIME = None


class RuntimeAnalysisBroker:
    def get_static_project_snapshot(
        self,
        bridge: Any,
        policy: StaticSnapshotPolicy | None = None,
    ) -> StaticProjectSnapshot:
        policy = policy or StaticSnapshotPolicy()
        if isinstance(bridge, TCPBridge):
            operation = (
                "project.snapshot.refresh"
                if policy.force_refresh
                else "project.snapshot.get"
            )
            data = _client_for_bridge(bridge).request(
                operation,
                {
                    "include_patterns": policy.include_patterns,
                    "include_playlist": policy.include_playlist,
                },
            ).data
            return StaticProjectSnapshot.from_dict(dict(data["snapshot"]))
        return local_runtime().get_static_project_snapshot(bridge, policy)

    def get_live_meter_window(
        self,
        bridge: Any,
        policy: LiveMeterPolicy | None = None,
        watcher_provider=None,
        static_snapshot: StaticProjectSnapshot | None = None,
    ) -> LiveMeterWindow:
        policy = policy or LiveMeterPolicy()
        if isinstance(bridge, TCPBridge) and static_snapshot is not None:
            data = _client_for_bridge(bridge).request(
                "analysis.live_meter.normalize",
                {
                    "policy": {
                        "ttl_seconds": policy.ttl_seconds,
                        "require_playing": policy.require_playing,
                        "min_capture_seconds": policy.min_capture_seconds,
                        "recent_watch_seconds": policy.recent_watch_seconds,
                    },
                    "watch_status": (
                        watcher_provider.status() if watcher_provider else {}
                    ),
                    "watch_last_max": (
                        watcher_provider.last_max() if watcher_provider else {}
                    ),
                    "static_snapshot": static_snapshot.to_dict(),
                },
            ).data
            return LiveMeterWindow.from_dict(dict(data["live_meter_window"]))
        return local_runtime().analysis_broker.get_live_meter_window(
            bridge,
            policy=policy,
            watcher_provider=watcher_provider,
            static_snapshot=static_snapshot,
        )


class RuntimeReportStore:
    def add_report(self, report: AnalysisReport) -> AnalysisReport:
        client = _default_client()
        if client is not None:
            data = client.request(
                "analysis.report.add",
                {"report": report.to_dict()},
            ).data
            return AnalysisReport.from_dict(dict(data["report"]))
        return local_runtime().add_report(report)

    def get_latest_report(self, workflow: str) -> AnalysisReport | None:
        client = _default_client()
        if client is not None:
            payload = client.latest_report(workflow)
            return AnalysisReport.from_dict(payload) if payload else None
        return local_runtime().report_store.get_latest_report(workflow)

    def clear(self) -> None:
        if _default_client() is not None:
            raise RuntimeClientError(
                "Clearing canonical Runtime reports is not exposed over TCP."
            )
        local_runtime().report_store.clear()


def local_runtime():
    global _LOCAL_RUNTIME
    if _LOCAL_RUNTIME is None:
        from .audio_worker import AudioAnalysisWorker
        from .core import RuntimeCore, resolve_job_worker_concurrency

        _LOCAL_RUNTIME = RuntimeCore(
            job_worker_concurrency=resolve_job_worker_concurrency()
        )
        AudioAnalysisWorker(_LOCAL_RUNTIME.audio_artifacts).register(_LOCAL_RUNTIME)
    return _LOCAL_RUNTIME


def _client_for_bridge(bridge: TCPBridge) -> RuntimeClient:
    return RuntimeClient(
        host=bridge.host,
        port=bridge.port,
        timeout=bridge.default_timeout + 5.0,
    )


def _default_client() -> RuntimeClient | None:
    if os.environ.get("FLS_PILOT_TRANSPORT", "direct").lower() != "tcp":
        return None
    return RuntimeClient()

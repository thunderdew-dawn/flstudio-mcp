"""Typed client for canonical Runtime services hosted by the daemon."""

from __future__ import annotations

import json
import os
import socket
import threading
from typing import Any

from ..connection import DEFAULT_TCP_HOST, DEFAULT_TCP_PORT
from .contracts import ProjectContext, RuntimeResponse, RuntimeSession
from .protocol import validate_runtime_request


class RuntimeClientError(RuntimeError):
    def __init__(self, message: str, *, code: str | None = None) -> None:
        super().__init__(message)
        self.code = code


class RuntimeClient:
    def __init__(
        self,
        host: str | None = None,
        port: int | None = None,
        *,
        timeout: float = 10.0,
    ) -> None:
        self.host = host or os.environ.get("FLS_PILOT_TCP_HOST", DEFAULT_TCP_HOST)
        self.port = int(port or os.environ.get("FLS_PILOT_TCP_PORT", DEFAULT_TCP_PORT))
        self.timeout = float(timeout)
        self._lock = threading.Lock()

    def request(
        self,
        operation: str,
        params: dict[str, Any] | None = None,
    ) -> RuntimeResponse:
        request = {"op": "runtime", "operation": operation, "params": params or {}}
        validate_runtime_request(request)
        try:
            payload = self._rpc(request)
        except OSError as exc:
            raise RuntimeClientError(
                f"Cannot reach Runtime at {self.host}:{self.port}: {exc}"
            ) from exc
        response = RuntimeResponse.from_dict(payload)
        if not response.ok:
            raise RuntimeClientError(
                response.error or "Runtime request failed",
                code=response.code,
            )
        return response

    def session(self) -> RuntimeSession:
        return RuntimeSession.from_dict(self.request("runtime.session").data["session"])

    def project_context(self) -> ProjectContext:
        return ProjectContext.from_dict(
            self.request("project.current").data["project_context"]
        )

    def workflow_catalog(self, *, include_inactive: bool = True) -> list[dict[str, Any]]:
        data = self.request(
            "workflow.catalog",
            {"include_inactive": include_inactive},
        ).data
        return [dict(row) for row in data.get("workflows") or ()]

    def latest_report(self, workflow_id: str) -> dict[str, Any] | None:
        return self.request(
            "analysis.report.latest",
            {"workflow_id": workflow_id},
        ).data.get("report")

    def run_workflow(
        self,
        workflow_id: str,
        *,
        inputs: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return dict(
            self.request(
                "analysis.workflow.run",
                {"workflow_id": workflow_id, "inputs": inputs or {}},
            ).data["result"]
        )

    def project_health(self) -> dict[str, Any]:
        return dict(self.request("analysis.health.get").data["health"])

    def _rpc(self, request: dict[str, Any]) -> dict[str, Any]:
        with self._lock, socket.create_connection(
            (self.host, self.port), timeout=self.timeout
        ) as connection:
            connection.settimeout(self.timeout)
            connection.sendall((json.dumps(request) + "\n").encode("utf-8"))
            payload = b""
            while b"\n" not in payload:
                chunk = connection.recv(65536)
                if not chunk:
                    break
                payload += chunk
        if not payload:
            raise RuntimeClientError("Runtime closed the connection without replying")
        decoded = json.loads(payload.split(b"\n", 1)[0].decode("utf-8"))
        if not isinstance(decoded, dict):
            raise RuntimeClientError("Runtime returned a non-object response")
        return decoded

"""Bounded execution and cooperative cancellation for Runtime jobs."""

from __future__ import annotations

import threading
from collections.abc import Callable, Mapping
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any

from .contracts import RuntimeJob
from .job_store import JobStore

JobHandler = Callable[[dict[str, Any], "JobContext"], Mapping[str, Any]]


class JobCancelled(RuntimeError):
    pass


@dataclass
class JobContext:
    job_id: str
    store: JobStore
    cancel_event: threading.Event

    @property
    def cancelled(self) -> bool:
        return self.cancel_event.is_set() or self.store.get(self.job_id).cancel_requested

    def raise_if_cancelled(self) -> None:
        if self.cancelled:
            raise JobCancelled("Runtime job was cancelled")

    def set_progress(self, progress: float) -> None:
        self.raise_if_cancelled()
        self.store.update_progress(self.job_id, progress)


class RuntimeJobQueue:
    def __init__(
        self,
        store: JobStore,
        *,
        max_workers: int = 1,
        result_validator: Callable[[dict[str, Any]], bool] | None = None,
    ) -> None:
        self.store = store
        self.max_workers = max(1, int(max_workers))
        self.recovery = self.store.recover(result_validator=result_validator)
        self._executor = ThreadPoolExecutor(
            max_workers=self.max_workers,
            thread_name_prefix="fls-audio-worker",
        )
        self._handlers: dict[str, JobHandler] = {}
        self._cancel_events: dict[str, threading.Event] = {}
        self._scheduled: set[str] = set()
        self._lock = threading.RLock()

    def register_handler(self, kind: str, handler: JobHandler) -> None:
        normalized = str(kind).strip()
        if not normalized:
            raise ValueError("job kind must not be empty")
        with self._lock:
            self._handlers[normalized] = handler
        for job in reversed(self.store.list(kind=normalized, status="queued", limit=500)):
            self._schedule(job.job_id)

    def submit(
        self,
        *,
        kind: str,
        input_payload: Mapping[str, Any],
        input_summary: Mapping[str, Any] | None = None,
        idempotency_key: str | None = None,
        idempotent: bool = True,
        max_retries: int = 1,
    ) -> RuntimeJob:
        normalized = str(kind).strip()
        with self._lock:
            if normalized not in self._handlers:
                raise ValueError(f"unknown Runtime job kind: {normalized!r}")
        job, cache_hit = self.store.create(
            kind=normalized,
            input_payload=input_payload,
            input_summary=input_summary or {},
            idempotency_key=idempotency_key,
            idempotent=idempotent,
            max_retries=max_retries,
        )
        if not cache_hit and job.status == "queued":
            self._schedule(job.job_id)
        return job

    def status(self, job_id: str) -> RuntimeJob:
        return self.store.get(job_id)

    def result(self, job_id: str) -> RuntimeJob:
        job = self.store.get(job_id)
        if job.status != "succeeded":
            raise ValueError(f"Runtime job result is not available: {job.status}")
        return job

    def cancel(self, job_id: str) -> RuntimeJob:
        job = self.store.cancel(job_id)
        with self._lock:
            event = self._cancel_events.get(job_id)
            if event is not None:
                event.set()
        return job

    def list(
        self,
        *,
        kind: str | None = None,
        status: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[RuntimeJob]:
        return self.store.list(kind=kind, status=status, limit=limit, offset=offset)

    def close(self, *, wait: bool = True) -> None:
        self._executor.shutdown(wait=wait, cancel_futures=False)
        self.store.close()

    def _schedule(self, job_id: str) -> None:
        with self._lock:
            if job_id in self._scheduled:
                return
            self._scheduled.add(job_id)
        self._executor.submit(self._run, job_id)

    def _run(self, job_id: str) -> None:
        cancel_event = threading.Event()
        with self._lock:
            self._cancel_events[job_id] = cancel_event
        try:
            job = self.store.mark_running(job_id)
            if job is None:
                return
            with self._lock:
                handler = self._handlers.get(job.kind)
            if handler is None:
                self.store.fail(
                    job_id,
                    {
                        "code": "job_handler_unavailable",
                        "message": f"No handler is registered for {job.kind!r}.",
                    },
                )
                return
            context = JobContext(job_id=job_id, store=self.store, cancel_event=cancel_event)
            context.raise_if_cancelled()
            result_ref = dict(handler(self.store.input_payload(job_id), context))
            context.raise_if_cancelled()
            self.store.complete(job_id, result_ref)
        except JobCancelled:
            self.store.mark_cancelled(job_id)
        except Exception as exc:
            self.store.fail(
                job_id,
                {
                    "code": "job_failed",
                    "type": type(exc).__name__,
                    "message": str(exc),
                },
            )
        finally:
            with self._lock:
                self._cancel_events.pop(job_id, None)
                self._scheduled.discard(job_id)

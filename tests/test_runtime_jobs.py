from __future__ import annotations

import time

from fls_pilot.runtime.job_store import JobStore
from fls_pilot.runtime.jobs import RuntimeJobQueue


def _wait_for(queue: RuntimeJobQueue, job_id: str, statuses: set[str], timeout: float = 2):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        job = queue.status(job_id)
        if job.status in statuses:
            return job
        time.sleep(0.01)
    raise AssertionError(f"job {job_id} did not reach {sorted(statuses)}")


def test_runtime_job_queue_completes_and_deduplicates(tmp_path) -> None:
    queue = RuntimeJobQueue(JobStore(tmp_path / "jobs.sqlite3"))
    queue.register_handler(
        "test.echo",
        lambda payload, context: {
            "kind": "inline-test-result",
            "value": payload["value"],
        },
    )
    try:
        first = queue.submit(
            kind="test.echo",
            input_payload={"value": 42},
            input_summary={"value": 42},
            idempotency_key="echo:42",
        )
        completed = _wait_for(queue, first.job_id, {"succeeded"})
        assert completed.progress == 1
        assert completed.result_ref == {"kind": "inline-test-result", "value": 42}

        duplicate = queue.submit(
            kind="test.echo",
            input_payload={"value": 42},
            input_summary={"value": 42},
            idempotency_key="echo:42",
        )
        assert duplicate.job_id == first.job_id
        assert duplicate.cache_hit is True
    finally:
        queue.close()


def test_runtime_job_queue_cancels_cooperatively(tmp_path) -> None:
    queue = RuntimeJobQueue(JobStore(tmp_path / "jobs.sqlite3"))

    def slow(_payload, context):
        for index in range(100):
            time.sleep(0.005)
            context.set_progress(index / 100)
        return {"unexpected": True}

    queue.register_handler("test.slow", slow)
    try:
        job = queue.submit(kind="test.slow", input_payload={}, input_summary={})
        _wait_for(queue, job.job_id, {"running"})
        requested = queue.cancel(job.job_id)
        assert requested.cancel_requested is True
        cancelled = _wait_for(queue, job.job_id, {"cancelled"})
        assert cancelled.finished_at is not None
    finally:
        queue.close()


def test_job_list_is_bounded_and_filterable(tmp_path) -> None:
    queue = RuntimeJobQueue(JobStore(tmp_path / "jobs.sqlite3"))
    queue.register_handler("test.echo", lambda payload, context: {"value": payload["value"]})
    try:
        jobs = [
            queue.submit(
                kind="test.echo",
                input_payload={"value": value},
                input_summary={"value": value},
            )
            for value in range(3)
        ]
        for job in jobs:
            _wait_for(queue, job.job_id, {"succeeded"})
        assert len(queue.list(kind="test.echo", status="succeeded", limit=2)) == 2
    finally:
        queue.close()

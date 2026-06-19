from __future__ import annotations

from fls_pilot.runtime.job_store import JobStore
from fls_pilot.runtime.jobs import RuntimeJobQueue


def _create_running_job(store: JobStore, *, idempotent: bool = True, max_retries: int = 1):
    job, _ = store.create(
        kind="test.recover",
        input_payload={"value": 1},
        input_summary={"value": 1},
        idempotency_key="recover:1",
        idempotent=idempotent,
        max_retries=max_retries,
    )
    assert store.mark_running(job.job_id) is not None
    return job


def test_queued_job_remains_queued_during_recovery(tmp_path) -> None:
    path = tmp_path / "jobs.sqlite3"
    first = JobStore(path)
    job, _ = first.create(
        kind="test.recover",
        input_payload={"value": 1},
        input_summary={"value": 1},
        idempotency_key="recover:queued",
        idempotent=True,
        max_retries=1,
    )
    first.close()

    queue = RuntimeJobQueue(JobStore(path))
    try:
        assert queue.status(job.job_id).status == "queued"
        assert queue.recovery == {
            "interrupted": 0,
            "requeued": 0,
            "succeeded": 0,
            "cancelled": 0,
            "failed": 0,
        }
    finally:
        queue.close()


def test_interrupted_idempotent_job_is_requeued(tmp_path) -> None:
    path = tmp_path / "jobs.sqlite3"
    first = JobStore(path)
    job = _create_running_job(first)
    first.close()

    recovered = JobStore(path)
    queue = RuntimeJobQueue(recovered)
    try:
        restored = queue.status(job.job_id)
        assert queue.recovery["interrupted"] == 1
        assert queue.recovery["requeued"] == 1
        assert restored.status == "queued"
        assert restored.retry_count == 1
    finally:
        queue.close()


def test_cancel_requested_job_is_cancelled_during_recovery(tmp_path) -> None:
    path = tmp_path / "jobs.sqlite3"
    first = JobStore(path)
    job = _create_running_job(first)
    first.cancel(job.job_id)
    first.close()

    queue = RuntimeJobQueue(JobStore(path))
    try:
        assert queue.status(job.job_id).status == "cancelled"
        assert queue.recovery["cancelled"] == 1
    finally:
        queue.close()


def test_non_idempotent_interrupted_job_fails_recovery(tmp_path) -> None:
    path = tmp_path / "jobs.sqlite3"
    first = JobStore(path)
    job = _create_running_job(first, idempotent=False, max_retries=0)
    first.close()

    queue = RuntimeJobQueue(JobStore(path))
    try:
        restored = queue.status(job.job_id)
        assert restored.status == "failed"
        assert restored.error["code"] == "job_recovery_failed"
    finally:
        queue.close()


def test_valid_committed_result_is_promoted_during_recovery(tmp_path) -> None:
    path = tmp_path / "jobs.sqlite3"
    first = JobStore(path)
    job = _create_running_job(first)
    result_ref = {"kind": "audio_features", "artifact_id": "artifact-ok"}
    first._update(job.job_id, result_ref=result_ref)
    first.close()

    queue = RuntimeJobQueue(
        JobStore(path),
        result_validator=lambda value: value == result_ref,
    )
    try:
        restored = queue.status(job.job_id)
        assert restored.status == "succeeded"
        assert restored.result_ref == result_ref
        assert queue.recovery["succeeded"] == 1
        assert queue.recovery["requeued"] == 0
    finally:
        queue.close()


def test_invalid_committed_result_fails_instead_of_requeueing(tmp_path) -> None:
    path = tmp_path / "jobs.sqlite3"
    first = JobStore(path)
    job = _create_running_job(first)
    first._update(
        job.job_id,
        result_ref={"kind": "audio_features", "artifact_id": "missing"},
    )
    first.close()

    queue = RuntimeJobQueue(JobStore(path), result_validator=lambda value: False)
    try:
        restored = queue.status(job.job_id)
        assert restored.status == "failed"
        assert restored.error["code"] == "job_recovery_result_invalid"
        assert queue.recovery["failed"] == 1
        assert queue.recovery["requeued"] == 0
    finally:
        queue.close()

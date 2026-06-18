"""SQLite-backed durable Runtime job state."""

from __future__ import annotations

import json
import sqlite3
import threading
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any
from uuid import uuid4

from .contracts import RuntimeJob, utc_now_iso

DEFAULT_JOB_STORE = Path.home() / ".fls-pilot" / "runtime" / "jobs.sqlite3"
class JobStore:
    def __init__(
        self,
        path: str | Path | None = None,
        *,
        busy_timeout_ms: int = 5000,
    ) -> None:
        self.path = Path(path or DEFAULT_JOB_STORE).expanduser()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._connection = sqlite3.connect(
            self.path,
            timeout=max(0.1, busy_timeout_ms / 1000),
            check_same_thread=False,
        )
        self._connection.row_factory = sqlite3.Row
        with self._connection:
            self._connection.execute("PRAGMA journal_mode=WAL")
            self._connection.execute(f"PRAGMA busy_timeout={int(busy_timeout_ms)}")
            self._connection.execute("PRAGMA synchronous=FULL")
            self._connection.execute(
                """
                CREATE TABLE IF NOT EXISTS jobs (
                    job_id TEXT PRIMARY KEY,
                    kind TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    started_at TEXT,
                    finished_at TEXT,
                    progress REAL NOT NULL DEFAULT 0,
                    input_summary TEXT NOT NULL,
                    input_payload TEXT NOT NULL,
                    result_ref TEXT,
                    error TEXT,
                    cancel_requested INTEGER NOT NULL DEFAULT 0,
                    cache_hit INTEGER NOT NULL DEFAULT 0,
                    retry_count INTEGER NOT NULL DEFAULT 0,
                    idempotency_key TEXT,
                    idempotent INTEGER NOT NULL DEFAULT 1,
                    max_retries INTEGER NOT NULL DEFAULT 1
                )
                """
            )
            self._connection.execute(
                "CREATE INDEX IF NOT EXISTS jobs_status_idx ON jobs(status, created_at)"
            )
            self._connection.execute(
                "CREATE INDEX IF NOT EXISTS jobs_kind_idx ON jobs(kind, created_at)"
            )
            self._connection.execute(
                "CREATE INDEX IF NOT EXISTS jobs_idempotency_idx "
                "ON jobs(idempotency_key, created_at)"
            )

    def close(self) -> None:
        with self._lock:
            self._connection.close()

    def create(
        self,
        *,
        kind: str,
        input_payload: Mapping[str, Any],
        input_summary: Mapping[str, Any],
        idempotency_key: str | None,
        idempotent: bool,
        max_retries: int,
    ) -> tuple[RuntimeJob, bool]:
        with self._lock, self._connection:
            if idempotency_key:
                row = self._connection.execute(
                    """
                    SELECT * FROM jobs
                    WHERE idempotency_key = ?
                      AND status IN ('queued', 'running', 'succeeded', 'interrupted')
                    ORDER BY created_at DESC
                    LIMIT 1
                    """,
                    (idempotency_key,),
                ).fetchone()
                if row is not None:
                    self._connection.execute(
                        "UPDATE jobs SET cache_hit = 1, updated_at = ? WHERE job_id = ?",
                        (utc_now_iso(), row["job_id"]),
                    )
                    return self.get(str(row["job_id"])), True
            now = utc_now_iso()
            job_id = f"job_{uuid4().hex}"
            self._connection.execute(
                """
                INSERT INTO jobs (
                    job_id, kind, status, created_at, updated_at, progress,
                    input_summary, input_payload, idempotency_key, idempotent,
                    max_retries
                ) VALUES (?, ?, 'queued', ?, ?, 0, ?, ?, ?, ?, ?)
                """,
                (
                    job_id,
                    str(kind),
                    now,
                    now,
                    _json(input_summary),
                    _json(input_payload),
                    idempotency_key,
                    int(bool(idempotent)),
                    max(0, int(max_retries)),
                ),
            )
            return self.get(job_id), False

    def get(self, job_id: str) -> RuntimeJob:
        with self._lock:
            row = self._connection.execute(
                "SELECT * FROM jobs WHERE job_id = ?",
                (str(job_id),),
            ).fetchone()
        if row is None:
            raise KeyError(f"unknown Runtime job: {job_id}")
        return self._to_job(row)

    def input_payload(self, job_id: str) -> dict[str, Any]:
        with self._lock:
            row = self._connection.execute(
                "SELECT input_payload FROM jobs WHERE job_id = ?",
                (str(job_id),),
            ).fetchone()
        if row is None:
            raise KeyError(f"unknown Runtime job: {job_id}")
        return _object(row["input_payload"])

    def list(
        self,
        *,
        kind: str | None = None,
        status: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[RuntimeJob]:
        clauses: list[str] = []
        values: list[Any] = []
        if kind:
            clauses.append("kind = ?")
            values.append(str(kind))
        if status:
            clauses.append("status = ?")
            values.append(str(status))
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        values.extend((max(1, min(500, int(limit))), max(0, int(offset))))
        with self._lock:
            rows = self._connection.execute(
                f"SELECT * FROM jobs{where} ORDER BY created_at DESC LIMIT ? OFFSET ?",
                values,
            ).fetchall()
        return [self._to_job(row) for row in rows]

    def mark_running(self, job_id: str) -> RuntimeJob | None:
        now = utc_now_iso()
        with self._lock, self._connection:
            cursor = self._connection.execute(
                """
                UPDATE jobs
                SET status = 'running', started_at = COALESCE(started_at, ?),
                    updated_at = ?, finished_at = NULL, error = NULL
                WHERE job_id = ? AND status = 'queued' AND cancel_requested = 0
                """,
                (now, now, str(job_id)),
            )
            if cursor.rowcount != 1:
                return None
            return self.get(job_id)

    def update_progress(self, job_id: str, progress: float) -> RuntimeJob:
        return self._update(job_id, progress=min(1.0, max(0.0, float(progress))))

    def complete(
        self,
        job_id: str,
        result_ref: Mapping[str, Any],
        *,
        cache_hit: bool = False,
    ) -> RuntimeJob:
        return self._update(
            job_id,
            status="succeeded",
            progress=1.0,
            result_ref=dict(result_ref),
            error=None,
            finished_at=utc_now_iso(),
            cache_hit=bool(cache_hit),
        )

    def fail(self, job_id: str, error: Mapping[str, Any]) -> RuntimeJob:
        return self._update(
            job_id,
            status="failed",
            error=dict(error),
            finished_at=utc_now_iso(),
        )

    def cancel(self, job_id: str) -> RuntimeJob:
        job = self.get(job_id)
        if job.status in {"succeeded", "failed", "cancelled", "expired"}:
            return job
        if job.status in {"queued", "interrupted"}:
            return self._update(
                job_id,
                status="cancelled",
                cancel_requested=True,
                finished_at=utc_now_iso(),
            )
        return self._update(job_id, cancel_requested=True)

    def mark_cancelled(self, job_id: str) -> RuntimeJob:
        return self._update(
            job_id,
            status="cancelled",
            cancel_requested=True,
            finished_at=utc_now_iso(),
        )

    def recover(
        self,
        *,
        result_validator: Callable[[dict[str, Any]], bool] | None = None,
    ) -> dict[str, int]:
        counts = {"interrupted": 0, "requeued": 0, "succeeded": 0, "cancelled": 0, "failed": 0}
        with self._lock, self._connection:
            now = utc_now_iso()
            cursor = self._connection.execute(
                "UPDATE jobs SET status = 'interrupted', updated_at = ? WHERE status = 'running'",
                (now,),
            )
            counts["interrupted"] = cursor.rowcount
            rows = self._connection.execute(
                "SELECT * FROM jobs WHERE status = 'interrupted' OR "
                "(status = 'queued' AND cancel_requested = 1)"
            ).fetchall()
            for row in rows:
                job_id = str(row["job_id"])
                if bool(row["cancel_requested"]):
                    self._connection.execute(
                        "UPDATE jobs SET status = 'cancelled', updated_at = ?, "
                        "finished_at = ? WHERE job_id = ?",
                        (now, now, job_id),
                    )
                    counts["cancelled"] += 1
                    continue
                result_ref = _optional_object(row["result_ref"])
                if result_ref and result_validator and result_validator(result_ref):
                    self._connection.execute(
                        "UPDATE jobs SET status = 'succeeded', progress = 1, "
                        "updated_at = ?, finished_at = ? WHERE job_id = ?",
                        (now, now, job_id),
                    )
                    counts["succeeded"] += 1
                elif bool(row["idempotent"]) and int(row["retry_count"]) < int(
                    row["max_retries"]
                ):
                    self._connection.execute(
                        "UPDATE jobs SET status = 'queued', retry_count = retry_count + 1, "
                        "updated_at = ?, started_at = NULL WHERE job_id = ?",
                        (now, job_id),
                    )
                    counts["requeued"] += 1
                else:
                    error = {
                        "code": "job_recovery_failed",
                        "message": "Interrupted job could not be recovered safely.",
                    }
                    self._connection.execute(
                        "UPDATE jobs SET status = 'failed', error = ?, updated_at = ?, "
                        "finished_at = ? WHERE job_id = ?",
                        (_json(error), now, now, job_id),
                    )
                    counts["failed"] += 1
        return counts

    def _update(self, job_id: str, **changes: Any) -> RuntimeJob:
        allowed = {
            "status",
            "progress",
            "result_ref",
            "error",
            "cancel_requested",
            "cache_hit",
            "finished_at",
        }
        unknown = set(changes) - allowed
        if unknown:
            raise ValueError(f"unsupported job fields: {sorted(unknown)}")
        assignments = ["updated_at = ?"]
        values: list[Any] = [utc_now_iso()]
        for key, value in changes.items():
            assignments.append(f"{key} = ?")
            if key in {"result_ref", "error"}:
                values.append(None if value is None else _json(value))
            elif key in {"cancel_requested", "cache_hit"}:
                values.append(int(bool(value)))
            else:
                values.append(value)
        values.append(str(job_id))
        with self._lock, self._connection:
            cursor = self._connection.execute(
                f"UPDATE jobs SET {', '.join(assignments)} WHERE job_id = ?",
                values,
            )
            if cursor.rowcount != 1:
                raise KeyError(f"unknown Runtime job: {job_id}")
        return self.get(job_id)

    @staticmethod
    def _to_job(row: sqlite3.Row, *, cache_hit: bool | None = None) -> RuntimeJob:
        return RuntimeJob(
            job_id=str(row["job_id"]),
            kind=str(row["kind"]),
            status=str(row["status"]),
            created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
            started_at=row["started_at"],
            finished_at=row["finished_at"],
            progress=float(row["progress"]),
            input_summary=_object(row["input_summary"]),
            result_ref=_optional_object(row["result_ref"]),
            error=_optional_object(row["error"]),
            cancel_requested=bool(row["cancel_requested"]),
            cache_hit=bool(row["cache_hit"]) if cache_hit is None else cache_hit,
            retry_count=int(row["retry_count"]),
            idempotency_key=row["idempotency_key"],
        )


def _json(value: Mapping[str, Any]) -> str:
    return json.dumps(dict(value), sort_keys=True, separators=(",", ":"))


def _object(value: str | None) -> dict[str, Any]:
    decoded = json.loads(value or "{}")
    if not isinstance(decoded, dict):
        raise ValueError("stored Runtime job JSON must be an object")
    return decoded


def _optional_object(value: str | None) -> dict[str, Any] | None:
    return None if value is None else _object(value)

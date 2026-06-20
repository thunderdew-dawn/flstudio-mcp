"""Workflow Run Store."""

import contextlib
import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .workflow_runs import WorkflowRun

DEFAULT_WORKFLOW_RUN_STORE = Path.home() / ".fls-pilot" / "runtime" / "workflow_runs.sqlite3"


class WorkflowRunStore:
    """SQLite-backed store for workflow runs."""

    def __init__(self, db_path: str | Path | None = None) -> None:
        self._db_path = str(Path(db_path or DEFAULT_WORKFLOW_RUN_STORE).expanduser())
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self) -> None:
        with contextlib.closing(sqlite3.connect(self._db_path)) as conn:
            with conn:
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS workflow_runs (
                      run_id TEXT PRIMARY KEY,
                      workflow_id TEXT NOT NULL,
                      workflow_version INTEGER NOT NULL,
                      status TEXT NOT NULL,
                      job_id TEXT,
                      report_id TEXT,
                      inputs_json TEXT NOT NULL,
                      result_json TEXT,
                      error_json TEXT,
                      created_at TEXT NOT NULL,
                      updated_at TEXT NOT NULL,
                      finished_at TEXT
                    )
                    """
                )
                conn.execute(
                    """
                    CREATE INDEX IF NOT EXISTS workflow_runs_workflow_idx
                    ON workflow_runs(workflow_id, created_at DESC)
                    """
                )
                conn.execute(
                    """
                    CREATE INDEX IF NOT EXISTS workflow_runs_job_idx
                    ON workflow_runs(job_id)
                    """
                )

    def create(
        self,
        workflow_id: str,
        workflow_version: int,
        inputs: dict[str, Any],
        job_id: str | None = None,
        status: str = "queued"
    ) -> WorkflowRun:
        """Create a new workflow run."""
        run_id = f"run_{uuid.uuid4().hex}"
        now = datetime.now(timezone.utc).isoformat()
        
        with contextlib.closing(sqlite3.connect(self._db_path)) as conn:
            with conn:
                conn.execute(
                    """
                    INSERT INTO workflow_runs (
                        run_id, workflow_id, workflow_version, status,
                        job_id, report_id, inputs_json, result_json, error_json,
                        created_at, updated_at, finished_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        run_id,
                        workflow_id,
                        workflow_version,
                        status,
                        job_id,
                        None,  # report_id
                        json.dumps(inputs),
                        None,  # result_json
                        None,  # error_json
                        now,
                        now,
                        None   # finished_at
                    )
                )
        return self.get(run_id)

    def get(self, run_id: str) -> WorkflowRun:
        """Get a workflow run by ID."""
        with contextlib.closing(sqlite3.connect(self._db_path)) as conn:
            with conn:
                cursor = conn.execute(
                    """
                    SELECT
                        run_id, workflow_id, workflow_version, status,
                        job_id, report_id, inputs_json, result_json, error_json,
                        created_at, updated_at, finished_at
                    FROM workflow_runs
                    WHERE run_id = ?
                    """,
                    (run_id,)
                )
                row = cursor.fetchone()
                if not row:
                    raise KeyError(f"Workflow run not found: {run_id}")
                return self._row_to_model(row)

    def update(
        self,
        run_id: str,
        *,
        status: str | None = None,
        job_id: str | None = None,
        report_id: str | None = None,
        result: dict[str, Any] | None = None,
        error: dict[str, Any] | None = None,
        finished_at: str | None = None
    ) -> WorkflowRun:
        """Update an existing workflow run."""
        now = datetime.now(timezone.utc).isoformat()
        
        # We fetch existing to selectively update
        existing = self.get(run_id)
        
        new_status = status if status is not None else existing.status
        new_job_id = job_id if job_id is not None else existing.job_id
        new_report_id = report_id if report_id is not None else existing.report_id
        new_result = result if result is not None else existing.result
        new_error = error if error is not None else existing.error
        new_finished_at = finished_at if finished_at is not None else existing.finished_at

        # If it finished and finished_at wasn't provided, set it now
        if new_status in ("succeeded", "failed", "cancelled") and not new_finished_at:
            new_finished_at = now

        with contextlib.closing(sqlite3.connect(self._db_path)) as conn:
            with conn:
                conn.execute(
                    """
                    UPDATE workflow_runs
                    SET status = ?, job_id = ?, report_id = ?,
                        result_json = ?, error_json = ?,
                        updated_at = ?, finished_at = ?
                    WHERE run_id = ?
                    """,
                    (
                        new_status,
                        new_job_id,
                        new_report_id,
                        json.dumps(new_result) if new_result is not None else None,
                        json.dumps(new_error) if new_error is not None else None,
                        now,
                        new_finished_at,
                        run_id
                    )
                )
        return self.get(run_id)

    def list(
        self,
        workflow_id: str | None = None,
        limit: int = 100,
        include_finished: bool = True
    ) -> tuple[WorkflowRun, ...]:
        """List workflow runs."""
        query = """
            SELECT
                run_id, workflow_id, workflow_version, status,
                job_id, report_id, inputs_json, result_json, error_json,
                created_at, updated_at, finished_at
            FROM workflow_runs
            WHERE 1=1
        """
        params: list[Any] = []
        
        if workflow_id:
            query += " AND workflow_id = ?"
            params.append(workflow_id)
            
        if not include_finished:
            query += " AND status NOT IN ('succeeded', 'failed', 'cancelled')"
            
        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        
        with contextlib.closing(sqlite3.connect(self._db_path)) as conn:
            with conn:
                cursor = conn.execute(query, tuple(params))
                return tuple(self._row_to_model(row) for row in cursor)

    def _row_to_model(self, row: Any) -> WorkflowRun:
        return WorkflowRun(
            run_id=row[0],
            workflow_id=row[1],
            workflow_version=row[2],
            status=row[3],
            job_id=row[4],
            report_id=row[5],
            inputs=json.loads(row[6]) if row[6] else {},
            result=json.loads(row[7]) if row[7] else None,
            error=json.loads(row[8]) if row[8] else None,
            created_at=row[9],
            updated_at=row[10],
            finished_at=row[11]
        )

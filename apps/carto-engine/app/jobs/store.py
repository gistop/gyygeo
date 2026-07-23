from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class JobStore:
    def __init__(self, database_path: Path) -> None:
        self.database_path = database_path

    def initialize(self) -> None:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY,
                    type TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    requested_by TEXT,
                    output_dir TEXT NOT NULL,
                    config_json TEXT NOT NULL,
                    result_json TEXT,
                    error TEXT,
                    log_path TEXT
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_created_at ON jobs(created_at)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status)")

    def create_job(
        self,
        *,
        job_id: str,
        job_type: str,
        requested_by: Optional[str],
        output_dir: Path,
        config: Dict[str, Any],
        log_path: Path,
    ) -> Dict[str, Any]:
        now = _now_iso()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO jobs (
                    id, type, status, created_at, updated_at, requested_by,
                    output_dir, config_json, result_json, error, log_path
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    job_id,
                    job_type,
                    "pending",
                    now,
                    now,
                    requested_by,
                    str(output_dir),
                    json.dumps(config, ensure_ascii=False),
                    None,
                    None,
                    str(log_path),
                ),
            )
        job = self.get_job(job_id)
        if job is None:
            raise RuntimeError(f"Failed to create job {job_id}")
        return job

    def update_job(
        self,
        job_id: str,
        *,
        status: Optional[str] = None,
        result: Optional[Dict[str, Any]] = None,
        error: Optional[str] = None,
    ) -> None:
        fields = ["updated_at = ?"]
        values: List[Any] = [_now_iso()]

        if status is not None:
            fields.append("status = ?")
            values.append(status)
        if result is not None:
            fields.append("result_json = ?")
            values.append(json.dumps(result, ensure_ascii=False))
        if error is not None:
            fields.append("error = ?")
            values.append(error)

        values.append(job_id)
        with self._connect() as conn:
            conn.execute(f"UPDATE jobs SET {', '.join(fields)} WHERE id = ?", values)

    def get_job(self, job_id: str) -> Optional[Dict[str, Any]]:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        if row is None:
            return None
        return self._row_to_job(row)

    def list_jobs(self, limit: int = 50) -> List[Dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM jobs ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [self._row_to_job(row) for row in rows]

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.database_path, timeout=30)
        conn.row_factory = sqlite3.Row
        return conn

    @staticmethod
    def _row_to_job(row: sqlite3.Row) -> Dict[str, Any]:
        result_json = row["result_json"]
        return {
            "id": row["id"],
            "type": row["type"],
            "status": row["status"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "requested_by": row["requested_by"],
            "output_dir": row["output_dir"],
            "config": json.loads(row["config_json"]),
            "result": json.loads(result_json) if result_json else None,
            "error": row["error"],
            "log_path": row["log_path"],
        }

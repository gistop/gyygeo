from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class DataStore:
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
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS datasets (
                    id TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    provider TEXT NOT NULL,
                    collection TEXT NOT NULL,
                    item_id TEXT NOT NULL,
                    type TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    path TEXT,
                    bbox_json TEXT NOT NULL,
                    crs TEXT,
                    resolution REAL,
                    bands_json TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    error TEXT
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_created_at ON jobs(created_at)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_datasets_created_at ON datasets(created_at)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_datasets_status ON datasets(status)")
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_datasets_source
                ON datasets(provider, collection, item_id)
                """
            )

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

    def create_dataset(
        self,
        *,
        dataset_id: str,
        provider: str,
        collection: str,
        item_id: str,
        dataset_type: str = "raster",
        bbox: List[float],
        bands: List[str],
        metadata: Dict[str, Any],
    ) -> Dict[str, Any]:
        now = _now_iso()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO datasets (
                    id, status, provider, collection, item_id, type, created_at, updated_at,
                    path, bbox_json, crs, resolution, bands_json, metadata_json, error
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    dataset_id,
                    "preparing",
                    provider,
                    collection,
                    item_id,
                    dataset_type,
                    now,
                    now,
                    None,
                    json.dumps(bbox, ensure_ascii=False),
                    None,
                    None,
                    json.dumps(bands, ensure_ascii=False),
                    json.dumps(metadata, ensure_ascii=False),
                    None,
                ),
            )
        dataset = self.get_dataset(dataset_id)
        if dataset is None:
            raise RuntimeError(f"Failed to create dataset {dataset_id}")
        return dataset

    def update_dataset(
        self,
        dataset_id: str,
        *,
        status: Optional[str] = None,
        path: Optional[Path] = None,
        bbox: Optional[List[float]] = None,
        crs: Optional[str] = None,
        resolution: Optional[float] = None,
        bands: Optional[List[str]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        error: Optional[str] = None,
    ) -> None:
        fields = ["updated_at = ?"]
        values: List[Any] = [_now_iso()]

        if status is not None:
            fields.append("status = ?")
            values.append(status)
        if path is not None:
            fields.append("path = ?")
            values.append(str(path))
        if bbox is not None:
            fields.append("bbox_json = ?")
            values.append(json.dumps(bbox, ensure_ascii=False))
        if crs is not None:
            fields.append("crs = ?")
            values.append(crs)
        if resolution is not None:
            fields.append("resolution = ?")
            values.append(resolution)
        if bands is not None:
            fields.append("bands_json = ?")
            values.append(json.dumps(bands, ensure_ascii=False))
        if metadata is not None:
            fields.append("metadata_json = ?")
            values.append(json.dumps(metadata, ensure_ascii=False))
        if error is not None:
            fields.append("error = ?")
            values.append(error)

        values.append(dataset_id)
        with self._connect() as conn:
            conn.execute(f"UPDATE datasets SET {', '.join(fields)} WHERE id = ?", values)

    def get_dataset(self, dataset_id: str) -> Optional[Dict[str, Any]]:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM datasets WHERE id = ?", (dataset_id,)).fetchone()
        if row is None:
            return None
        return self._row_to_dataset(row)

    def list_datasets(self, limit: int = 50) -> List[Dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM datasets ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [self._row_to_dataset(row) for row in rows]

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

    @staticmethod
    def _row_to_dataset(row: sqlite3.Row) -> Dict[str, Any]:
        return {
            "id": row["id"],
            "status": row["status"],
            "provider": row["provider"],
            "collection": row["collection"],
            "item_id": row["item_id"],
            "type": row["type"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "path": row["path"],
            "bbox": json.loads(row["bbox_json"]),
            "crs": row["crs"],
            "resolution": row["resolution"],
            "bands": json.loads(row["bands_json"]),
            "metadata": json.loads(row["metadata_json"]),
            "error": row["error"],
        }

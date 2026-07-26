from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path


_SAFE_NAME_PATTERN = re.compile(r"[^a-zA-Z0-9_.-]+")


def utc_timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def safe_name(value: str) -> str:
    cleaned = _SAFE_NAME_PATTERN.sub("-", value.strip()).strip(".-")
    return cleaned or "unnamed"


def job_output_dir(base_output_dir: Path, job_id: str, job_name: str) -> Path:
    return base_output_dir / "jobs" / f"{utc_timestamp()}_{safe_name(job_name)}_{job_id[:8]}"


def prepared_dataset_path(prepared_dir: Path, dataset_id: str) -> Path:
    return prepared_dir / f"{safe_name(dataset_id)}.tif"


def download_dataset_dir(cache_dir: Path, dataset_id: str) -> Path:
    return cache_dir / "downloads" / safe_name(dataset_id)

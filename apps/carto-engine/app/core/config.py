from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Optional


def _int_env(name: str, default: int) -> int:
    raw = _env(name)
    if raw is None or raw.strip() == "":
        return default
    return int(raw)


def _env(name: str, default: Optional[str] = None) -> Optional[str]:
    legacy_name = name.replace("GYYGEO_CARTO_", "GYYCARTO_")
    value = os.getenv(name)
    if value is not None:
        return value
    return os.getenv(legacy_name, default)


def _path_env(name: str, default: str) -> Path:
    return Path(os.path.expandvars(_env(name, default) or default))


def _csv_env(name: str, default: str) -> list[str]:
    raw = _env(name, default) or default
    return [item.strip() for item in raw.split(",") if item.strip()]


def _load_env_file(path: Path) -> None:
    if not path.exists():
        return

    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def _default_project_python() -> Path:
    local_app_data = Path(os.getenv("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    return local_app_data / "ESRI" / "conda" / "envs" / "gyygeo-carto-py3" / "python.exe"


@dataclass(frozen=True)
class Settings:
    app_name: str
    environment: str
    host: str
    port: int
    api_prefix: str
    python_exe: Path
    max_workers: int
    job_timeout_seconds: int
    arcpy_mode: str
    base_dir: Path
    data_dir: Path
    output_dir: Path
    log_dir: Path
    template_dir: Path
    database_path: Path
    cors_origins: list[str]

    @classmethod
    def from_env(cls) -> "Settings":
        base_dir = Path(__file__).resolve().parents[2]
        _load_env_file(base_dir / ".env")

        data_dir = _path_env("GYYGEO_CARTO_DATA_DIR", str(base_dir / "data"))
        output_dir = _path_env("GYYGEO_CARTO_OUTPUT_DIR", str(base_dir / "outputs"))
        log_dir = _path_env("GYYGEO_CARTO_LOG_DIR", str(base_dir / "logs"))
        template_dir = _path_env("GYYGEO_CARTO_TEMPLATE_DIR", str(base_dir / "templates"))

        return cls(
            app_name="gyygeo-carto-engine",
            environment=_env("GYYGEO_CARTO_ENV", "development"),
            host=_env("GYYGEO_CARTO_HOST", "127.0.0.1"),
            port=_int_env("GYYGEO_CARTO_PORT", 8000),
            api_prefix=_env("GYYGEO_CARTO_API_PREFIX", "/api/v1"),
            python_exe=_path_env("GYYGEO_CARTO_PYTHON_EXE", str(_default_project_python())),
            max_workers=max(1, _int_env("GYYGEO_CARTO_MAX_WORKERS", 1)),
            job_timeout_seconds=max(0, _int_env("GYYGEO_CARTO_JOB_TIMEOUT_SECONDS", 1800)),
            arcpy_mode=_env("GYYGEO_CARTO_ARCPY_MODE", "required").lower(),
            base_dir=base_dir,
            data_dir=data_dir,
            output_dir=output_dir,
            log_dir=log_dir,
            template_dir=template_dir,
            database_path=_path_env("GYYGEO_CARTO_DATABASE_PATH", str(data_dir / "jobs.sqlite3")),
            cors_origins=_csv_env(
                "GYYGEO_CARTO_CORS_ORIGINS",
                "http://127.0.0.1:5173,http://localhost:5173,"
                "http://127.0.0.1:5174,http://localhost:5174,"
                "http://127.0.0.1:5175,http://localhost:5175",
            ),
        )

    def ensure_directories(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.template_dir.mkdir(parents=True, exist_ok=True)
        (self.template_dir / "aprx").mkdir(parents=True, exist_ok=True)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings.from_env()

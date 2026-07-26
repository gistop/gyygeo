from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Optional


def _env(name: str, default: Optional[str] = None) -> Optional[str]:
    legacy_name = name.replace("GYYGEO_DATA_", "GYYDATA_")
    value = os.getenv(name)
    if value is not None:
        return value
    return os.getenv(legacy_name, default)


def _int_env(name: str, default: int) -> int:
    raw = _env(name)
    if raw is None or raw.strip() == "":
        return default
    return int(raw)


def _path_env(name: str, default: str) -> Path:
    return Path(os.path.expandvars(_env(name, default) or default))


def _load_env_file(path: Path) -> None:
    if not path.exists():
        return

    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


@dataclass(frozen=True)
class Settings:
    app_name: str
    environment: str
    host: str
    port: int
    api_prefix: str
    max_workers: int
    base_dir: Path
    data_dir: Path
    cache_dir: Path
    prepared_dir: Path
    log_dir: Path
    database_path: Path
    mpc_stac_url: str

    @classmethod
    def from_env(cls) -> "Settings":
        base_dir = Path(__file__).resolve().parents[2]
        _load_env_file(base_dir / ".env")

        data_dir = _path_env("GYYGEO_DATA_DATA_DIR", str(base_dir / "data"))
        cache_dir = _path_env("GYYGEO_DATA_CACHE_DIR", str(base_dir / "cache"))
        prepared_dir = _path_env("GYYGEO_DATA_PREPARED_DIR", str(cache_dir / "prepared"))
        log_dir = _path_env("GYYGEO_DATA_LOG_DIR", str(base_dir / "logs"))

        return cls(
            app_name="gyygeo-data-service",
            environment=_env("GYYGEO_DATA_ENV", "development") or "development",
            host=_env("GYYGEO_DATA_HOST", "127.0.0.1") or "127.0.0.1",
            port=_int_env("GYYGEO_DATA_PORT", 8010),
            api_prefix=_env("GYYGEO_DATA_API_PREFIX", "/api/v1") or "/api/v1",
            max_workers=max(1, _int_env("GYYGEO_DATA_MAX_WORKERS", 2)),
            base_dir=base_dir,
            data_dir=data_dir,
            cache_dir=cache_dir,
            prepared_dir=prepared_dir,
            log_dir=log_dir,
            database_path=_path_env("GYYGEO_DATA_DATABASE_PATH", str(data_dir / "data.sqlite3")),
            mpc_stac_url=_env(
                "GYYGEO_DATA_MPC_STAC_URL",
                "https://planetarycomputer.microsoft.com/api/stac/v1",
            )
            or "https://planetarycomputer.microsoft.com/api/stac/v1",
        )

    def ensure_directories(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.prepared_dir.mkdir(parents=True, exist_ok=True)
        self.log_dir.mkdir(parents=True, exist_ok=True)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings.from_env()


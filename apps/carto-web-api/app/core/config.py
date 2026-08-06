from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Optional


def _env(name: str, default: Optional[str] = None) -> Optional[str]:
    value = os.getenv(name)
    if value is not None:
        return value
    return default


def _int_env(name: str, default: int) -> int:
    raw = _env(name)
    if raw is None or raw.strip() == "":
        return default
    return int(raw)


def _csv_env(name: str, default: str) -> list[str]:
    raw = _env(name, default) or default
    return [item.strip() for item in raw.split(",") if item.strip()]


def _secret_env(name: str, placeholders: set[str]) -> Optional[str]:
    raw = _env(name)
    if raw is None:
        return None
    value = raw.strip()
    if not value or value in placeholders:
        return None
    return value


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
    base_dir: Path
    deepseek_api_key: Optional[str]
    deepseek_base_url: str
    deepseek_model: str
    deepseek_timeout_seconds: int
    cors_origins: list[str]
    data_service_url: str
    carto_engine_url: str
    tianditu_token: Optional[str]
    tianditu_cva_w_wmts_url: str
    tianditu_vec_w_wmts_url: str

    @classmethod
    def from_env(cls) -> "Settings":
        base_dir = Path(__file__).resolve().parents[2]
        _load_env_file(base_dir / ".env")

        return cls(
            app_name="gyygeo-carto-web-api",
            environment=_env("GYYGEO_WEB_API_ENV", "development") or "development",
            host=_env("GYYGEO_WEB_API_HOST", "127.0.0.1") or "127.0.0.1",
            port=_int_env("GYYGEO_WEB_API_PORT", 8020),
            api_prefix=_env("GYYGEO_WEB_API_API_PREFIX", "/api/v1") or "/api/v1",
            base_dir=base_dir,
            deepseek_api_key=_env(
                "GYYGEO_WEB_API_DEEPSEEK_API_KEY",
                os.getenv("DEEPSEEK_API_KEY"),
            ),
            deepseek_base_url=(
                _env("GYYGEO_WEB_API_DEEPSEEK_BASE_URL", "https://api.deepseek.com")
                or "https://api.deepseek.com"
            ).rstrip("/"),
            deepseek_model=(
                _env("GYYGEO_WEB_API_DEEPSEEK_MODEL", "deepseek-v4-flash")
                or "deepseek-v4-flash"
            ),
            deepseek_timeout_seconds=max(
                5,
                _int_env("GYYGEO_WEB_API_DEEPSEEK_TIMEOUT_SECONDS", 60),
            ),
            cors_origins=_csv_env(
                "GYYGEO_WEB_API_CORS_ORIGINS",
                "http://127.0.0.1:5173,http://localhost:5173,"
                "http://127.0.0.1:5174,http://localhost:5174,"
                "http://127.0.0.1:5175,http://localhost:5175",
            ),
            data_service_url=(
                _env("GYYGEO_WEB_API_DATA_SERVICE_URL", "http://127.0.0.1:8010")
                or "http://127.0.0.1:8010"
            ).rstrip("/"),
            carto_engine_url=(
                _env("GYYGEO_WEB_API_CARTO_ENGINE_URL", "http://127.0.0.1:8000")
                or "http://127.0.0.1:8000"
            ).rstrip("/"),
            tianditu_token=_secret_env(
                "GYYGEO_WEB_API_TIANDITU_TOKEN",
                {"您的密钥", "your-token", "your-token-here"},
            ),
            tianditu_cva_w_wmts_url=(
                _env(
                    "GYYGEO_WEB_API_TIANDITU_CVA_W_WMTS_URL",
                    "http://t0.tianditu.gov.cn/cva_w/wmts",
                )
                or "http://t0.tianditu.gov.cn/cva_w/wmts"
            ),
            tianditu_vec_w_wmts_url=(
                _env(
                    "GYYGEO_WEB_API_TIANDITU_VEC_W_WMTS_URL",
                    "http://t0.tianditu.gov.cn/vec_w/wmts",
                )
                or "http://t0.tianditu.gov.cn/vec_w/wmts"
            ),
        )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings.from_env()

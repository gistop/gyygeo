from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any, Dict

from app.core.config import Settings
from app.core.models import model_to_dict
from app.arcpy_engine.environment import probe_arcpy
from app.schemas.project import RenderPreviewRequest


class ArcPyRenderer:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def render_preview(
        self,
        *,
        job_id: str,
        request: RenderPreviewRequest,
        output_dir: Path,
        log_path: Path,
    ) -> Dict[str, Any]:
        output_dir.mkdir(parents=True, exist_ok=True)
        self._write_json(output_dir / "config.json", model_to_dict(request))

        if request.dry_run:
            log_path.write_text("Dry run completed. ArcPy was not imported.\n", encoding="utf-8")
            return {
                "job_id": job_id,
                "mode": "dry_run",
                "files": {
                    "config": str(output_dir / "config.json"),
                    "log": str(log_path),
                },
            }

        if self.settings.arcpy_mode not in {"required", "auto"}:
            raise ValueError(
                "GYYGEO_CARTO_ARCPY_MODE must be 'required' or 'auto' for real rendering."
            )

        arcpy_probe = probe_arcpy(self.settings.python_exe, self.settings.base_dir)
        if not arcpy_probe.get("available"):
            raise RuntimeError(
                "ArcPy runtime is unavailable. "
                f"Probe result: {json.dumps(arcpy_probe, ensure_ascii=False)}"
            )

        return self._render_with_worker(
            job_id=job_id,
            request=request,
            output_dir=output_dir,
            log_path=log_path,
        )

    def _render_with_worker(
        self,
        *,
        job_id: str,
        request: RenderPreviewRequest,
        output_dir: Path,
        log_path: Path,
    ) -> Dict[str, Any]:
        result_path = output_dir / "result.json"
        command = [
            str(self.settings.python_exe),
            "-u",
            "-X",
            "faulthandler",
            "-m",
            "app.arcpy_engine.worker",
            "--job-id",
            job_id,
            "--config",
            str(output_dir / "config.json"),
            "--output-dir",
            str(output_dir),
            "--result",
            str(result_path),
        ]
        timeout = self.settings.job_timeout_seconds or None

        completed = subprocess.run(
            command,
            cwd=str(self.settings.base_dir),
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        log_path.write_text(
            "COMMAND:\n"
            + " ".join(command)
            + "\n\nSTDOUT:\n"
            + completed.stdout
            + "\nSTDERR:\n"
            + completed.stderr,
            encoding="utf-8",
        )

        if completed.returncode != 0:
            raise RuntimeError(
                "ArcPy worker failed with return code "
                f"{completed.returncode}. See log: {log_path}"
            )
        if not result_path.exists():
            raise RuntimeError(f"ArcPy worker did not create result file: {result_path}")

        return json.loads(result_path.read_text(encoding="utf-8"))

    @staticmethod
    def _write_json(path: Path, payload: Dict[str, Any]) -> None:
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

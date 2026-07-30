from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict

from app.arcpy_engine.environment import probe_arcpy
from app.core.config import Settings
from app.core.models import model_to_dict
from app.schemas.arcpy_code import ArcPyCodeRequest


class ArcPyCodeRunner:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def run_code(
        self,
        *,
        job_id: str,
        request: ArcPyCodeRequest,
        output_dir: Path,
        log_path: Path,
    ) -> Dict[str, Any]:
        output_dir.mkdir(parents=True, exist_ok=True)
        self._write_json(output_dir / "config.json", model_to_dict(request))

        if self.settings.arcpy_mode not in {"required", "auto"}:
            raise ValueError(
                "GYYGEO_CARTO_ARCPY_MODE must be 'required' or 'auto' for ArcPy code jobs."
            )

        arcpy_probe = probe_arcpy(self.settings.python_exe, self.settings.base_dir)
        if not arcpy_probe.get("available"):
            raise RuntimeError(
                "ArcPy runtime is unavailable. "
                f"Probe result: {json.dumps(arcpy_probe, ensure_ascii=False)}"
            )

        return self._run_with_subprocess(
            job_id=job_id,
            request=request,
            output_dir=output_dir,
            log_path=log_path,
        )

    def _run_with_subprocess(
        self,
        *,
        job_id: str,
        request: ArcPyCodeRequest,
        output_dir: Path,
        log_path: Path,
    ) -> Dict[str, Any]:
        template_path = self.settings.template_dir / "aprx" / f"{request.template_id}.aprx"
        if not template_path.exists():
            raise FileNotFoundError(f"APRX template not found: {template_path}")

        extension = "jpg" if request.output_format in {"jpg", "jpeg"} else request.output_format
        work_aprx = output_dir / "workspace.aprx"
        output_path = output_dir / f"output.{extension}"
        script_path = output_dir / "run.py"
        stdout_path = output_dir / "stdout.txt"
        stderr_path = output_dir / "stderr.txt"
        result_path = output_dir / "result.json"

        shutil.copy2(template_path, work_aprx)
        script_path.write_text(
            _script_source(
                code=request.code,
                aprx_path=work_aprx,
                output_dir=output_dir,
                output_path=output_path,
                context=request.context,
                dpi=request.dpi,
            ),
            encoding="utf-8",
        )

        command = [str(self.settings.python_exe), str(script_path)]
        timeout = self.settings.job_timeout_seconds or None
        try:
            completed = subprocess.run(
                command,
                cwd=str(output_dir),
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            stdout_path.write_text(_process_output_text(exc.stdout), encoding="utf-8")
            stderr_path.write_text(_process_output_text(exc.stderr), encoding="utf-8")
            raise TimeoutError(f"ArcPy code job timed out after {timeout} seconds.") from exc

        stdout_path.write_text(completed.stdout, encoding="utf-8")
        stderr_path.write_text(completed.stderr, encoding="utf-8")
        log_path.write_text(
            "COMMAND:\n"
            + " ".join(command)
            + "\n\nSTDOUT:\n"
            + completed.stdout
            + "\nSTDERR:\n"
            + completed.stderr,
            encoding="utf-8",
        )

        result = {
            "job_id": job_id,
            "mode": "arcpy_code",
            "summary": f"Executed ArcPy code with return code {completed.returncode}.",
            "returncode": completed.returncode,
            "files": {
                "script": str(script_path),
                "stdout": str(stdout_path),
                "stderr": str(stderr_path),
                "work_aprx": str(work_aprx),
                "preview": str(output_path) if output_path.exists() else None,
                "config": str(output_dir / "config.json"),
                "log": str(log_path),
                "result": str(result_path),
            },
        }
        result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

        if completed.returncode != 0:
            raise RuntimeError(
                f"ArcPy code failed with return code {completed.returncode}. "
                f"See stderr: {stderr_path}"
            )
        if not output_path.exists():
            raise RuntimeError(f"ArcPy code did not create output: {output_path}")
        return result

    @staticmethod
    def _write_json(path: Path, payload: Dict[str, Any]) -> None:
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _script_source(
    *,
    code: str,
    aprx_path: Path,
    output_dir: Path,
    output_path: Path,
    context: Any,
    dpi: int,
) -> str:
    context_json = json.dumps(context or {}, ensure_ascii=False, indent=2)
    return (
        "from __future__ import annotations\n\n"
        "import json\n"
        "from pathlib import Path\n\n"
        f"APRX_PATH = r{str(aprx_path)!r}\n"
        f"OUTPUT_DIR = Path(r{str(output_dir)!r})\n"
        f"OUTPUT_PATH = r{str(output_path)!r}\n"
        f"DPI = {int(dpi)}\n"
        f"CONTEXT = json.loads({context_json!r})\n\n"
        "# LLM generated ArcPy code starts here.\n"
        f"{code.rstrip()}\n"
        "# LLM generated ArcPy code ends here.\n"
    )


def _process_output_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)

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

        typography_files = {}
        if request.text_styles or request.layout_elements or request.layout_operations:
            typography_files = self._run_typography_postprocess(
                request=request,
                work_aprx=work_aprx,
                output_path=output_path,
                output_dir=output_dir,
            )

        if typography_files:
            result["files"] = {**result["files"], **typography_files}
            result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        return result

    def _run_typography_postprocess(
        self,
        *,
        request: ArcPyCodeRequest,
        work_aprx: Path,
        output_path: Path,
        output_dir: Path,
    ) -> Dict[str, str]:
        script_path = output_dir / "postprocess_typography.py"
        stdout_path = output_dir / "postprocess_typography_stdout.txt"
        stderr_path = output_dir / "postprocess_typography_stderr.txt"
        script_path.write_text(
            _typography_postprocess_source(
                base_dir=self.settings.base_dir,
                aprx_path=work_aprx,
                output_path=output_path,
                output_format=request.output_format,
                dpi=request.dpi,
                text_styles=[style.model_dump() for style in request.text_styles],
                layout_elements=[element.model_dump() for element in request.layout_elements],
                layout_operations=[operation.model_dump() for operation in request.layout_operations],
            ),
            encoding="utf-8",
        )

        completed = subprocess.run(
            [str(self.settings.python_exe), str(script_path)],
            cwd=str(self.settings.base_dir),
            capture_output=True,
            text=True,
            timeout=self.settings.job_timeout_seconds or None,
            check=False,
        )
        stdout_path.write_text(completed.stdout, encoding="utf-8")
        stderr_path.write_text(completed.stderr, encoding="utf-8")
        if completed.returncode != 0:
            raise RuntimeError(
                "ArcPy typography postprocess failed with return code "
                f"{completed.returncode}. See stderr: {stderr_path}"
            )
        return {
            "typography_script": str(script_path),
            "typography_stdout": str(stdout_path),
            "typography_stderr": str(stderr_path),
        }

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


def _typography_postprocess_source(
    *,
    base_dir: Path,
    aprx_path: Path,
    output_path: Path,
    output_format: str,
    dpi: int,
    text_styles: list[Dict[str, Any]],
    layout_elements: list[Dict[str, Any]] | None = None,
    layout_operations: list[Dict[str, Any]] | None = None,
) -> str:
    styles_json = json.dumps(text_styles, ensure_ascii=False, indent=2)
    elements_json = json.dumps(layout_elements or [], ensure_ascii=False, indent=2)
    operations_json = json.dumps(layout_operations or [], ensure_ascii=False, indent=2)
    return (
        "from __future__ import annotations\n\n"
        "import json\n"
        "import sys\n"
        f"sys.path.insert(0, r{str(base_dir)!r})\n\n"
        "import arcpy\n"
        "from app.arcpy_engine.typography import apply_text_typography_operations\n"
        "from app.arcpy_engine.worker import _apply_layout_element_positions, _apply_layout_operations\n"
        "from app.schemas.project import LayoutElementPosition, LayoutOperation, TextTypography\n\n"
        f"APRX_PATH = r{str(aprx_path)!r}\n"
        f"OUTPUT_PATH = r{str(output_path)!r}\n"
        f"OUTPUT_FORMAT = {output_format!r}\n"
        f"DPI = {int(dpi)}\n"
        f"TEXT_STYLES = json.loads({styles_json!r})\n\n"
        f"LAYOUT_ELEMENTS = json.loads({elements_json!r})\n\n"
        f"LAYOUT_OPERATIONS = json.loads({operations_json!r})\n\n"
        "aprx = arcpy.mp.ArcGISProject(APRX_PATH)\n"
        "try:\n"
        "    layout = aprx.listLayouts()[0]\n"
        "    map_obj = aprx.listMaps()[0]\n"
        "    styles = [TextTypography(**item) for item in TEXT_STYLES]\n"
        "    layout_elements = [LayoutElementPosition(**item) for item in LAYOUT_ELEMENTS]\n"
        "    layout_operations = [LayoutOperation(**item) for item in LAYOUT_OPERATIONS]\n"
        "    messages = []\n"
        "    messages.extend(apply_text_typography_operations(layout, styles))\n"
        "    messages.extend(_apply_layout_operations(arcpy, aprx, layout, map_obj, layout_operations))\n"
        "    messages.extend(_apply_layout_element_positions(layout, layout_elements))\n"
        "    for message in messages:\n"
        "        print(message)\n"
        "    aprx.save()\n"
        "    if OUTPUT_FORMAT == 'png':\n"
        "        layout.exportToPNG(OUTPUT_PATH, resolution=DPI)\n"
        "    elif OUTPUT_FORMAT == 'pdf':\n"
        "        layout.exportToPDF(OUTPUT_PATH, resolution=DPI)\n"
        "    else:\n"
        "        layout.exportToJPEG(OUTPUT_PATH, resolution=DPI)\n"
        "finally:\n"
        "    del aprx\n"
    )


def _process_output_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)

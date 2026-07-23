from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any, Dict


def probe_arcpy(python_exe: Path, working_dir: Path, timeout_seconds: int = 30) -> Dict[str, Any]:
    code = (
        "import arcpy; "
        "install_info = arcpy.GetInstallInfo(); "
        "print(install_info.get('Version', 'unknown')); "
        "print(install_info.get('ProductName', 'unknown')); "
        "print(arcpy.ProductInfo())"
    )
    try:
        completed = subprocess.run(
            [str(python_exe), "-c", code],
            cwd=str(working_dir),
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
        lines = [line.strip() for line in completed.stdout.splitlines() if line.strip()]
        if completed.returncode != 0:
            return {
                "available": False,
                "python": str(python_exe),
                "return_code": completed.returncode,
                "stdout": completed.stdout.strip(),
                "stderr": completed.stderr.strip(),
            }
        return {
            "available": True,
            "python": str(python_exe),
            "version": lines[0] if len(lines) > 0 else None,
            "product_name": lines[1] if len(lines) > 1 else None,
            "license": lines[2] if len(lines) > 2 else None,
        }
    except subprocess.TimeoutExpired:
        return {
            "available": False,
            "python": str(python_exe),
            "error": f"ArcPy probe timed out after {timeout_seconds} seconds.",
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "available": False,
            "python": str(python_exe),
            "error": str(exc),
        }

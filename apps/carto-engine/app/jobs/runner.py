from __future__ import annotations

import logging
import traceback
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Dict
from uuid import uuid4

from app.arcpy_engine.renderer import ArcPyRenderer
from app.core.models import model_to_dict
from app.jobs.store import JobStore
from app.schemas.project import RenderPreviewRequest
from app.storage.paths import job_output_dir


logger = logging.getLogger(__name__)


class JobRunner:
    def __init__(
        self,
        *,
        store: JobStore,
        renderer: ArcPyRenderer,
        output_root: Path,
        max_workers: int,
    ) -> None:
        self.store = store
        self.renderer = renderer
        self.output_root = output_root
        self.executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="carto-job")

    def submit_render_preview(self, request: RenderPreviewRequest) -> Dict[str, Any]:
        job_id = uuid4().hex
        output_dir = job_output_dir(self.output_root, job_id, request.project.project_name)
        log_path = output_dir / "job.log"
        config = model_to_dict(request)

        job = self.store.create_job(
            job_id=job_id,
            job_type="render_preview",
            requested_by=request.requested_by,
            output_dir=output_dir,
            config=config,
            log_path=log_path,
        )
        self.executor.submit(self._run_render_preview, job_id, request, output_dir, log_path)
        return job

    def shutdown(self) -> None:
        self.executor.shutdown(wait=True, cancel_futures=False)

    def _run_render_preview(
        self,
        job_id: str,
        request: RenderPreviewRequest,
        output_dir: Path,
        log_path: Path,
    ) -> None:
        self.store.update_job(job_id, status="running")
        try:
            result = self.renderer.render_preview(
                job_id=job_id,
                request=request,
                output_dir=output_dir,
                log_path=log_path,
            )
            self.store.update_job(job_id, status="done", result=result, error="")
        except Exception as exc:  # noqa: BLE001
            logger.exception("Render job %s failed", job_id)
            output_dir.mkdir(parents=True, exist_ok=True)
            runner_traceback = "RUNNER TRACEBACK:\n" + traceback.format_exc()
            if log_path.exists() and log_path.stat().st_size > 0:
                with log_path.open("a", encoding="utf-8") as log_file:
                    log_file.write("\n\n" + runner_traceback)
            else:
                log_path.write_text(runner_traceback, encoding="utf-8")
            self.store.update_job(job_id, status="failed", error=str(exc))

from __future__ import annotations

import logging
import traceback
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Dict
from uuid import uuid4

from app.core.models import model_to_dict
from app.jobs.store import DataStore
from app.providers.registry import ProviderRegistry
from app.schemas.download import DownloadAssetsRequest
from app.schemas.prepare import PrepareRasterRequest
from app.storage.paths import download_dataset_dir, job_output_dir, prepared_dataset_path


logger = logging.getLogger(__name__)


class PrepareJobRunner:
    def __init__(
        self,
        *,
        store: DataStore,
        providers: ProviderRegistry,
        output_root: Path,
        prepared_dir: Path,
        max_workers: int,
    ) -> None:
        self.store = store
        self.providers = providers
        self.output_root = output_root
        self.prepared_dir = prepared_dir
        self.executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="data-job")

    def submit_prepare_raster(self, request: PrepareRasterRequest) -> Dict[str, Any]:
        job_id = uuid4().hex
        dataset_id = "ds_" + uuid4().hex
        output_dir = job_output_dir(self.output_root, job_id, request.item_id)
        log_path = output_dir / "job.log"
        output_path = prepared_dataset_path(self.prepared_dir, dataset_id)
        config = model_to_dict(request)

        self.store.create_dataset(
            dataset_id=dataset_id,
            provider=request.provider,
            collection=request.collection,
            item_id=request.item_id,
            bbox=request.bbox,
            bands=request.bands,
            metadata={
                "job_id": job_id,
                "target_resolution": request.target_resolution,
                "target_crs": request.target_crs,
                **request.metadata,
            },
        )
        job = self.store.create_job(
            job_id=job_id,
            job_type="prepare_raster",
            requested_by=request.requested_by,
            output_dir=output_dir,
            config={**config, "dataset_id": dataset_id},
            log_path=log_path,
        )
        self.executor.submit(
            self._run_prepare_raster,
            job_id,
            dataset_id,
            request,
            output_path,
            log_path,
        )
        return job

    def submit_download_assets(self, request: DownloadAssetsRequest) -> Dict[str, Any]:
        job_id = uuid4().hex
        dataset_id = "ds_" + uuid4().hex
        output_dir = job_output_dir(self.output_root, job_id, request.item_id)
        log_path = output_dir / "job.log"
        download_dir = download_dataset_dir(self.output_root, dataset_id)
        config = model_to_dict(request)

        self.store.create_dataset(
            dataset_id=dataset_id,
            provider=request.provider,
            collection=request.collection,
            item_id=request.item_id,
            dataset_type="asset_bundle",
            bbox=[],
            bands=request.assets,
            metadata={"job_id": job_id, **request.metadata},
        )
        job = self.store.create_job(
            job_id=job_id,
            job_type="download_assets",
            requested_by=request.requested_by,
            output_dir=output_dir,
            config={**config, "dataset_id": dataset_id},
            log_path=log_path,
        )
        self.executor.submit(
            self._run_download_assets,
            job_id,
            dataset_id,
            request,
            download_dir,
            log_path,
        )
        return job

    def shutdown(self) -> None:
        self.executor.shutdown(wait=True, cancel_futures=False)

    def _run_prepare_raster(
        self,
        job_id: str,
        dataset_id: str,
        request: PrepareRasterRequest,
        output_path: Path,
        log_path: Path,
    ) -> None:
        self.store.update_job(job_id, status="running")
        try:
            provider = self.providers.get(request.provider)
            prepared = provider.prepare_raster(request, output_path)
            dataset = {
                "dataset_id": dataset_id,
                "type": "raster",
                "path": str(prepared.path),
                "bbox": prepared.bbox,
                "crs": prepared.crs,
                "resolution": prepared.resolution,
                "bands": prepared.bands,
                "metadata": prepared.metadata,
            }
            self.store.update_dataset(
                dataset_id,
                status="ready",
                path=prepared.path,
                bbox=prepared.bbox,
                crs=prepared.crs,
                resolution=prepared.resolution,
                bands=prepared.bands,
                metadata={**prepared.metadata, **request.metadata},
                error="",
            )
            self.store.update_job(job_id, status="done", result={"dataset": dataset}, error="")
            log_path.parent.mkdir(parents=True, exist_ok=True)
            log_path.write_text("Prepare raster job completed.\n", encoding="utf-8")
        except Exception as exc:  # noqa: BLE001
            logger.exception("Prepare job %s failed", job_id)
            log_path.parent.mkdir(parents=True, exist_ok=True)
            log_path.write_text(traceback.format_exc(), encoding="utf-8")
            self.store.update_dataset(dataset_id, status="failed", error=str(exc))
            self.store.update_job(job_id, status="failed", error=str(exc))

    def _run_download_assets(
        self,
        job_id: str,
        dataset_id: str,
        request: DownloadAssetsRequest,
        download_dir: Path,
        log_path: Path,
    ) -> None:
        self.store.update_job(job_id, status="running")
        try:
            provider = self.providers.get(request.provider)
            downloaded = provider.download_assets(request, download_dir)  # type: ignore[attr-defined]
            assets = [
                {
                    "key": asset.key,
                    "path": str(asset.path),
                    "size_bytes": asset.size_bytes,
                    "media_type": asset.media_type,
                }
                for asset in downloaded.assets
            ]
            result = {
                "dataset": {
                    "dataset_id": dataset_id,
                    "type": "asset_bundle",
                    "path": str(downloaded.output_dir),
                    "assets": assets,
                    "metadata": downloaded.metadata,
                }
            }
            self.store.update_dataset(
                dataset_id,
                status="ready",
                path=downloaded.output_dir,
                bands=request.assets,
                metadata={**downloaded.metadata, **request.metadata, "assets": assets},
                error="",
            )
            self.store.update_job(job_id, status="done", result=result, error="")
            log_path.parent.mkdir(parents=True, exist_ok=True)
            log_path.write_text("Download assets job completed.\n", encoding="utf-8")
        except Exception as exc:  # noqa: BLE001
            logger.exception("Download job %s failed", job_id)
            log_path.parent.mkdir(parents=True, exist_ok=True)
            log_path.write_text(traceback.format_exc(), encoding="utf-8")
            self.store.update_dataset(dataset_id, status="failed", error=str(exc))
            self.store.update_job(job_id, status="failed", error=str(exc))

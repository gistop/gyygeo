from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

from app.agents.cartography.skills.remote_sensing_basemap.schema import (
    RemoteSensingBasemapPolicy,
    RemoteSensingBasemapPrepareRequest,
)


@lru_cache(maxsize=1)
def load_remote_sensing_basemap_policy() -> RemoteSensingBasemapPolicy:
    path = Path(__file__).with_name("policy.json")
    return RemoteSensingBasemapPolicy.model_validate_json(path.read_text(encoding="utf-8"))


def build_prepare_payload(
    map_spec: dict[str, Any],
    selected_item: dict[str, Any],
    policy: RemoteSensingBasemapPolicy | None = None,
) -> dict[str, Any]:
    policy = policy or load_remote_sensing_basemap_policy()
    item = selected_item["item"]
    basemap = map_spec["basemap"]
    study_area = map_spec["study_area"]
    prepare_strategy = basemap.get("raster_source_strategy") or policy.prepare_strategy
    request = RemoteSensingBasemapPrepareRequest(
        provider=basemap["provider"],
        collection=basemap["collection"],
        item_id=item["item_id"],
        bbox=study_area["bbox"],
        geometry=study_area.get("geometry"),
        bbox_crs=policy.bbox_crs,
        bands=basemap.get("bands") or policy.default_bands,
        target_resolution=basemap.get("target_resolution") or policy.default_target_resolution,
        target_crs=basemap.get("target_crs") or policy.default_target_crs,
        requested_by=policy.requested_by,
        output={"format": policy.output_format, "purpose": policy.output_purpose},
        metadata={
            "agent_task_kind": str(map_spec.get("map_kind") or "expert_tool_call"),
            "prepare_strategy": prepare_strategy,
            "fallback_strategy": policy.fallback_strategy,
            "skill_id": policy.skill_id,
            **(
                {"overview_index": basemap["overview_index"]}
                if basemap.get("overview_index") is not None
                else {}
            ),
        },
    )
    return request.model_dump(exclude_none=True)


def prepared_dataset_path(prepare_result: dict[str, Any]) -> str | None:
    dataset = prepare_result.get("dataset") or {}
    path = dataset.get("path")
    return path if isinstance(path, str) and path else None

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.agents.cartography.skills.data_acquisition.schema import (
    CandidateImage,
    DataAcquisitionPolicy,
    DataAcquisitionSearchRequest,
    ImageSelection,
    PendingImageSelectionAction,
)


@lru_cache(maxsize=1)
def load_data_acquisition_policy() -> DataAcquisitionPolicy:
    path = Path(__file__).with_name("policy.json")
    return DataAcquisitionPolicy.model_validate_json(path.read_text(encoding="utf-8"))


def build_search_payload(
    map_spec: dict[str, Any],
    policy: DataAcquisitionPolicy | None = None,
) -> dict[str, Any]:
    policy = policy or load_data_acquisition_policy()
    basemap = map_spec["basemap"]
    study_area = map_spec["study_area"]
    limit = int(basemap.get("limit") or policy.default_limit)
    request = DataAcquisitionSearchRequest(
        provider=str(basemap.get("provider") or policy.default_provider),
        collection=str(basemap.get("collection") or ""),
        bbox=study_area["bbox"],
        geometry=study_area.get("geometry"),
        datetime=basemap.get("datetime"),
        limit=max(policy.min_limit, min(policy.max_limit, limit)),
        cloud_cover_lte=basemap.get("cloud_cover_lte"),
    )
    return request.model_dump(exclude_none=True)


def select_recommended_item(
    items: list[dict[str, Any]],
    policy: DataAcquisitionPolicy | None = None,
) -> dict[str, Any]:
    policy = policy or load_data_acquisition_policy()
    if policy.selection_strategy != "lowest_cloud_cover_then_earliest_datetime":
        raise ValueError(f"Unsupported image selection strategy: {policy.selection_strategy}")

    def sort_key(item: dict[str, Any]) -> tuple[float, str]:
        cloud = item.get("cloud_cover")
        cloud_value = float(cloud) if isinstance(cloud, (int, float)) else 999.0
        return cloud_value, str(item.get("datetime") or "")

    selected = sorted(items, key=sort_key)[0]
    image = CandidateImage.model_validate(selected)
    selection = ImageSelection(
        summary=(
            f"Recommended image {image.item_id} with cloud cover "
            f"{selected.get('cloud_cover', 'unknown')}."
        ),
        item=selected,
    )
    return selection.model_dump()


def build_pending_image_selection(
    recommended_item: dict[str, Any],
    policy: DataAcquisitionPolicy | None = None,
) -> dict[str, Any]:
    policy = policy or load_data_acquisition_policy()
    item = recommended_item.get("item")
    recommended_item_id = item.get("item_id") if isinstance(item, dict) else None
    action = PendingImageSelectionAction(
        message=policy.candidate_message,
        recommended_item_id=(
            str(recommended_item_id)
            if isinstance(recommended_item_id, str) and recommended_item_id
            else None
        ),
    )
    return json.loads(action.model_dump_json(exclude_none=True))


def selected_item_from_search(search_result: dict[str, Any], item_id: str) -> dict[str, Any]:
    items = search_result.get("items")
    if not isinstance(items, list):
        raise RuntimeError("Expert search result does not include candidate items.")
    for item in items:
        if isinstance(item, dict) and item.get("item_id") == item_id:
            image = CandidateImage.model_validate(item)
            return ImageSelection(
                summary=f"Selected image {image.item_id} from user selection.",
                item=item,
            ).model_dump()
    raise ValueError(f"Selected image {item_id} was not found in this task's search results.")


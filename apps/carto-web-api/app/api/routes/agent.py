from __future__ import annotations

import json
import re
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field


router = APIRouter(prefix="/agent", tags=["agent"])

TaskStatus = Literal["queued", "running", "waiting_for_user", "done", "failed"]
StepStatus = Literal["pending", "running", "done", "failed"]
LayoutAnchor = Literal[
    "bottom_left",
    "bottom_center",
    "bottom_right",
    "middle_left",
    "center",
    "middle_right",
    "top_left",
    "top_center",
    "top_right",
]
PageSizeName = Literal["a0", "a1", "a2", "a3", "a4", "letter", "legal"]
PageOrientation = Literal["portrait", "landscape"]

_tasks: dict[str, "AgentTask"] = {}
_tasks_lock = threading.Lock()
_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="carto-agent")

_NORTH_ARROW_ELEMENT_NAME = "zbz"
_DEFAULT_LAYOUT_ELEMENT_INSET = 0.3
_ANCHOR_PATTERNS: list[tuple[LayoutAnchor, tuple[str, ...]]] = [
    ("bottom_left", ("左下角", "左下", "lower left", "bottom left")),
    ("bottom_right", ("右下角", "右下", "lower right", "bottom right")),
    ("top_left", ("左上角", "左上", "upper left", "top left")),
    ("top_right", ("右上角", "右上", "upper right", "top right")),
    ("bottom_center", ("下方居中", "底部居中", "底端居中", "bottom center")),
    ("top_center", ("上方居中", "顶部居中", "顶端居中", "top center")),
    ("middle_left", ("左侧居中", "左边居中", "左中", "middle left")),
    ("middle_right", ("右侧居中", "右边居中", "右中", "middle right")),
    ("center", ("页面中间", "版面中间", "居中", "中间", "center")),
]


class AgentChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=12000)


class PolygonGeometry(BaseModel):
    type: Literal["Polygon"]
    coordinates: List[List[List[float]]]


class AgentPageContext(BaseModel):
    provider: str = "mpc"
    collection: str
    datetime: Optional[str] = None
    cloud_cover_lte: Optional[float] = None
    limit: int = Field(default=10, ge=1, le=100)
    aoi_mode: Literal["rectangle", "polygon"] = "rectangle"
    bbox: List[float] = Field(min_length=4, max_length=4)
    geometry: Optional[PolygonGeometry] = None
    bands: List[str] = Field(default_factory=lambda: ["red", "green", "blue"])
    target_resolution: Optional[float] = None
    target_crs: Optional[str] = None
    map_title: Optional[str] = None
    layout_name: Optional[str] = None


class AgentChatRequest(BaseModel):
    messages: List[AgentChatMessage] = Field(min_length=1, max_length=30)
    context: Optional[AgentPageContext] = None


class AgentStep(BaseModel):
    name: str
    status: StepStatus = "pending"
    summary: str = ""
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    input: Dict[str, Any] = Field(default_factory=dict)
    output: Dict[str, Any] = Field(default_factory=dict)
    error: Optional[str] = None


class AgentTask(BaseModel):
    id: str
    kind: str
    status: TaskStatus
    created_at: str
    updated_at: str
    message: str
    map_spec: Dict[str, Any] = Field(default_factory=dict)
    steps: List[AgentStep] = Field(default_factory=list)
    outputs: Dict[str, Any] = Field(default_factory=dict)
    error: Optional[str] = None


class AgentChatResponse(BaseModel):
    message: AgentChatMessage
    model: str = "gyygeo-agent-0.1"
    task: Optional[AgentTask] = None
    requires_confirmation: bool = False


@router.post("/chat", response_model=AgentChatResponse)
def chat(request: Request, payload: AgentChatRequest) -> AgentChatResponse:
    user_message = _latest_user_message(payload.messages)
    if not user_message:
        raise HTTPException(status_code=400, detail="A user message is required.")

    if not _is_supported_agent_request(user_message):
        return AgentChatResponse(
            message=AgentChatMessage(
                role="assistant",
                content=(
                    "I can run the research-area overview map workflow now. "
                    "Try: make a research area overview map from the current AOI, "
                    "using remote sensing imagery, output jpg. You can also ask me to "
                    "move the north arrow, for example: 把指北针放到左下角."
                ),
            )
        )

    if payload.context is None or not _valid_bbox(payload.context.bbox):
        return AgentChatResponse(
            message=AgentChatMessage(
                role="assistant",
                content=(
                    "I need a confirmed study-area boundary before starting. "
                    "Please draw a rectangle or polygon on the map, then send the request again."
                ),
            ),
            requires_confirmation=True,
        )

    task = _create_task(user_message, payload.context)
    settings = request.app.state.settings
    _executor.submit(_run_research_area_overview_task, task.id, settings)

    return AgentChatResponse(
        message=AgentChatMessage(
            role="assistant",
            content=(
                f"Started research-area overview map task {task.id}. "
                "I am using the current map AOI as the study-area boundary and will produce a jpg output."
            ),
        ),
        task=task,
    )


@router.post("/expert/chat", response_model=AgentChatResponse)
def expert_chat(request: Request, payload: AgentChatRequest) -> AgentChatResponse:
    user_message = _latest_user_message(payload.messages)
    if not user_message:
        raise HTTPException(status_code=400, detail="A user message is required.")

    settings = request.app.state.settings
    code = _extract_python_code(user_message)
    if code is None:
        code = _generate_expert_arcpy_code(user_message, payload.context, settings)

    task = _create_expert_task(user_message, payload.context, code)
    _executor.submit(_run_expert_arcpy_code_task, task.id, settings)

    return AgentChatResponse(
        message=AgentChatMessage(
            role="assistant",
            content=(
                f"Started expert ArcPy code task {task.id}. "
                "I saved the generated script and am running it against a copied APRX."
            ),
        ),
        model="gyygeo-expert-arcpy-0.1",
        task=task,
    )


@router.get("/tasks/{task_id}", response_model=AgentTask)
def get_task(task_id: str) -> AgentTask:
    task = _get_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Agent task not found.")
    return task


def _latest_user_message(messages: List[AgentChatMessage]) -> str:
    for message in reversed(messages):
        if message.role == "user":
            return message.content
    return ""


def _is_research_area_overview_request(message: str) -> bool:
    lowered = message.lower()
    keywords = [
        "\u7814\u7a76\u533a",
        "\u793a\u610f\u56fe",
        "\u9065\u611f",
        "\u5f71\u50cf",
        "overview map",
        "research area",
        "remote sensing",
    ]
    return any(keyword in lowered for keyword in keywords)


def _is_supported_agent_request(message: str) -> bool:
    return (
        _is_research_area_overview_request(message)
        or bool(_extract_layout_elements(message))
        or bool(_extract_layout_page(message))
    )


def _create_task(message: str, context: AgentPageContext) -> AgentTask:
    now = _now()
    task_id = "agent_" + uuid4().hex
    study_area_name = _extract_study_area_name(message)
    output_format = _extract_output_format(message)
    layout_elements = _extract_layout_elements(message)
    layout_page = _extract_layout_page(message)
    title = context.map_title or (
        f"{study_area_name} Research Area Overview Map"
        if study_area_name
        else "Research Area Overview Map"
    )
    map_spec = {
        "schema_version": "0.1",
        "map_kind": "research_area_overview",
        "study_area": {
            "name": study_area_name,
            "boundary_source": "current_map_aoi",
            "aoi_mode": context.aoi_mode,
            "bbox": context.bbox,
            "geometry": context.geometry.model_dump() if context.geometry else None,
        },
        "basemap": {
            "type": "remote_sensing",
            "provider": context.provider,
            "collection": context.collection,
            "datetime": context.datetime,
            "cloud_cover_lte": context.cloud_cover_lte,
            "bands": context.bands,
            "target_resolution": context.target_resolution,
            "target_crs": context.target_crs,
        },
        "layout": {
            "title": title,
            "template_id": "default",
            "layout_name": context.layout_name,
            "fit_padding": 0.08,
            "layout_elements": layout_elements,
            "page": layout_page or None,
        },
        "output": {
            "format": output_format,
            "dpi": 300 if output_format in {"jpg", "pdf"} else 150,
        },
    }
    task = AgentTask(
        id=task_id,
        kind="research_area_overview",
        status="queued",
        created_at=now,
        updated_at=now,
        message="Task queued.",
        map_spec=map_spec,
        steps=[
            AgentStep(name="validate_map_spec"),
            AgentStep(name="search_remote_sensing_images"),
            AgentStep(name="select_best_image"),
            AgentStep(name="prepare_remote_sensing_basemap"),
            AgentStep(name="write_study_area_boundary"),
            AgentStep(name="render_research_area_overview_map"),
            AgentStep(name="check_map_output"),
        ],
    )
    _save_task(task)
    return task


def _create_expert_task(
    message: str,
    context: Optional[AgentPageContext],
    code: str,
) -> AgentTask:
    now = _now()
    task_id = "expert_" + uuid4().hex
    template_id = "default"
    map_spec = {
        "schema_version": "0.1",
        "map_kind": "expert_arcpy_code",
        "template_id": template_id,
        "context": context.model_dump() if context else None,
        "output": {
            "format": "jpg",
            "dpi": 300,
        },
    }
    task = AgentTask(
        id=task_id,
        kind="expert_arcpy_code",
        status="queued",
        created_at=now,
        updated_at=now,
        message="Expert ArcPy code task queued.",
        map_spec=map_spec,
        steps=[
            AgentStep(
                name="run_arcpy_code",
                input={
                    "code_preview": code[:2000],
                    "code_length": len(code),
                },
            ),
            AgentStep(name="check_expert_output"),
        ],
        outputs={"code": code},
    )
    _save_task(task)
    return task


def _run_research_area_overview_task(task_id: str, settings: Any) -> None:
    task = _require_task(task_id)
    try:
        _set_task_status(task, "running", "Running research-area overview workflow.")
        _run_step(task, "validate_map_spec", lambda: _tool_validate_map_spec(task.map_spec))

        search_result = _run_step(
            task,
            "search_remote_sensing_images",
            lambda: _tool_search_remote_sensing_images(task.map_spec, settings.data_service_url),
        )
        _merge_task_outputs(task, {"search": search_result})
        selected_item = _run_step(
            task,
            "select_best_image",
            lambda: _tool_select_best_image(search_result),
        )
        _merge_task_outputs(task, {"selected_item": selected_item})
        prepare_result = _run_step(
            task,
            "prepare_remote_sensing_basemap",
            lambda: _tool_prepare_remote_sensing_basemap(
                task.map_spec,
                selected_item,
                settings.data_service_url,
            ),
        )
        _merge_task_outputs(task, {"prepared_dataset": prepare_result})
        boundary_result = _run_step(
            task,
            "write_study_area_boundary",
            lambda: _tool_write_study_area_boundary(task.map_spec, settings.base_dir, task.id),
        )
        _merge_task_outputs(task, {"boundary": boundary_result})
        render_result = _run_step(
            task,
            "render_research_area_overview_map",
            lambda: _tool_render_research_area_overview_map(
                task.map_spec,
                prepare_result,
                boundary_result,
                settings.carto_engine_url,
            ),
        )
        _merge_task_outputs(task, {"render": render_result})
        qa_result = _run_step(
            task,
            "check_map_output",
            lambda: _tool_check_map_output(task.map_spec, prepare_result, render_result),
        )
        _merge_task_outputs(task, {"qa": qa_result})
        _set_task_status(task, "done", "Research-area overview map completed.")
    except Exception as exc:  # noqa: BLE001
        task.error = _agent_error_message(exc)
        _set_task_status(task, "failed", f"Research-area overview map failed: {task.error}")


def _run_expert_arcpy_code_task(task_id: str, settings: Any) -> None:
    task = _require_task(task_id)
    try:
        _set_task_status(task, "running", "Running expert ArcPy code.")
        run_result = _run_step(
            task,
            "run_arcpy_code",
            lambda: _tool_run_arcpy_code(
                task.map_spec,
                str(task.outputs["code"]),
                settings,
                task.id,
            ),
        )
        _merge_task_outputs(task, {"run": run_result})
        check_result = _run_step(
            task,
            "check_expert_output",
            lambda: _tool_check_expert_output(run_result),
        )
        _merge_task_outputs(task, {"qa": check_result})
        _set_task_status(task, "done", "Expert ArcPy code completed.")
    except Exception as exc:  # noqa: BLE001
        task.error = str(exc)
        _set_task_status(task, "failed", f"Expert ArcPy code failed: {task.error}")


def _run_step(task: AgentTask, name: str, fn: Any) -> Dict[str, Any]:
    step = _find_step(task, name)
    step.status = "running"
    step.started_at = _now()
    step.error = None
    task.updated_at = _now()
    _save_task(task)
    try:
        result = fn()
        step.status = "done"
        step.finished_at = _now()
        step.output = result
        step.summary = result.get("summary", "")
        task.updated_at = _now()
        _save_task(task)
        return result
    except Exception as exc:  # noqa: BLE001
        step.status = "failed"
        step.finished_at = _now()
        step.error = str(exc)
        task.updated_at = _now()
        _save_task(task)
        raise


def _merge_task_outputs(task: AgentTask, outputs: Dict[str, Any]) -> None:
    task.outputs = {**task.outputs, **outputs}
    task.updated_at = _now()
    _save_task(task)


def _agent_error_message(exc: Exception) -> str:
    message = str(exc)
    if "remote HTTPS COG reads" in message:
        return (
            "Data preparation failed because the data-service GDAL/rasterio runtime cannot "
            "open signed Microsoft Planetary Computer COG assets over HTTPS. The agent "
            "successfully selected an image, but cannot prepare the remote-sensing basemap "
            "until the geospatial runtime supports remote COG reads or an explicit "
            "asset-cache/download policy is added."
        )
    return message


def _tool_validate_map_spec(map_spec: Dict[str, Any]) -> Dict[str, Any]:
    bbox = map_spec["study_area"]["bbox"]
    if not _valid_bbox(bbox):
        raise ValueError("Study-area bbox is invalid.")
    if not map_spec["basemap"]["collection"]:
        raise ValueError("Remote-sensing collection is required.")
    if not map_spec["basemap"]["bands"]:
        raise ValueError("At least one raster band is required.")
    return {"summary": "Map spec is valid.", "bbox": bbox}


def _tool_search_remote_sensing_images(
    map_spec: Dict[str, Any],
    data_service_url: str,
) -> Dict[str, Any]:
    payload = {
        "provider": map_spec["basemap"]["provider"],
        "collection": map_spec["basemap"]["collection"],
        "bbox": map_spec["study_area"]["bbox"],
        "geometry": map_spec["study_area"].get("geometry"),
        "datetime": map_spec["basemap"].get("datetime"),
        "limit": 10,
        "cloud_cover_lte": map_spec["basemap"].get("cloud_cover_lte"),
    }
    payload = {key: value for key, value in payload.items() if value is not None}
    response = _post_json(f"{data_service_url}/api/v1/searches", payload)
    items = response.get("items") or []
    if not items:
        raise RuntimeError("No remote-sensing images found for the current AOI and filters.")
    return {
        "summary": f"Found {len(items)} candidate image item(s).",
        "items": items,
        "request": payload,
    }


def _tool_select_best_image(search_result: Dict[str, Any]) -> Dict[str, Any]:
    items = search_result["items"]

    def sort_key(item: Dict[str, Any]) -> tuple[float, str]:
        cloud = item.get("cloud_cover")
        cloud_value = float(cloud) if isinstance(cloud, (int, float)) else 999.0
        return cloud_value, str(item.get("datetime") or "")

    selected = sorted(items, key=sort_key)[0]
    return {
        "summary": (
            "Selected image "
            f"{selected.get('item_id')} with cloud cover {selected.get('cloud_cover', 'unknown')}."
        ),
        "item": selected,
    }


def _tool_prepare_remote_sensing_basemap(
    map_spec: Dict[str, Any],
    selected_item: Dict[str, Any],
    data_service_url: str,
) -> Dict[str, Any]:
    item = selected_item["item"]
    payload = {
        "provider": map_spec["basemap"]["provider"],
        "collection": map_spec["basemap"]["collection"],
        "item_id": item["item_id"],
        "bbox": map_spec["study_area"]["bbox"],
        "geometry": map_spec["study_area"].get("geometry"),
        "bbox_crs": "EPSG:4326",
        "bands": map_spec["basemap"]["bands"],
        "target_resolution": map_spec["basemap"].get("target_resolution"),
        "target_crs": map_spec["basemap"].get("target_crs"),
        "requested_by": "gyygeo-agent",
        "output": {"format": "geotiff", "purpose": "carto-render"},
        "metadata": {
            "agent_task_kind": "research_area_overview",
            "prepare_strategy": "mpc_dynamic_tiles",
        },
    }
    payload = {key: value for key, value in payload.items() if value is not None}
    response = _post_json(f"{data_service_url}/api/v1/prepare-jobs", payload)
    job = _poll_job(data_service_url, response["job"]["id"], timeout_seconds=240)
    dataset = (job.get("result") or {}).get("dataset") or {}
    path = dataset.get("path")
    if job.get("status") != "done" or not path:
        raise RuntimeError(f"Prepare job did not produce a dataset: {job.get('error') or job}")
    return {
        "summary": f"Prepared basemap dataset {dataset.get('dataset_id')}.",
        "job_id": job["id"],
        "dataset": dataset,
    }


def _tool_write_study_area_boundary(
    map_spec: Dict[str, Any],
    base_dir: Path,
    task_id: str,
) -> Dict[str, Any]:
    geometry = map_spec["study_area"].get("geometry") or _bbox_geometry(map_spec["study_area"]["bbox"])
    output_dir = base_dir / "data" / "agent" / task_id
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / "study-area.geojson"
    feature_collection = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {"name": map_spec["study_area"].get("name") or "Study Area"},
                "geometry": geometry,
            }
        ],
    }
    path.write_text(json.dumps(feature_collection, ensure_ascii=False, indent=2), encoding="utf-8")
    return {
        "summary": "Wrote study-area boundary GeoJSON.",
        "path": str(path),
    }


def _tool_render_research_area_overview_map(
    map_spec: Dict[str, Any],
    prepare_result: Dict[str, Any],
    boundary_result: Dict[str, Any],
    carto_engine_url: str,
) -> Dict[str, Any]:
    dataset_path = prepare_result["dataset"]["path"]
    title = map_spec["layout"]["title"]
    project_name = _slug_name(title) or "research-area-overview"
    payload = {
        "requested_by": "gyygeo-agent",
        "dry_run": False,
        "project": {
            "project_name": project_name,
            "template_id": map_spec["layout"].get("template_id") or "default",
            "title": title,
            "layers": [
                {
                    "id": "remote-sensing-basemap",
                    "name": "Remote Sensing Basemap",
                    "data_source": dataset_path,
                    "visible": True,
                    "opacity": 1,
                },
            ],
            "fit_to_layers": True,
            "fit_layer_names": ["Remote Sensing Basemap"],
            "fit_padding": map_spec["layout"].get("fit_padding", 0.08),
            "layout_elements": map_spec["layout"].get("layout_elements") or [],
            "page": map_spec["layout"].get("page"),
            "export": {
                "format": map_spec["output"]["format"],
                "dpi": map_spec["output"]["dpi"],
                "layout_name": map_spec["layout"].get("layout_name"),
            },
            "metadata": {
                "agent_task_kind": "research_area_overview",
                "study_area_boundary_geojson": boundary_result["path"],
            },
        },
    }
    response = _post_json(f"{carto_engine_url}/api/v1/render/preview", payload)
    job = _poll_job(carto_engine_url, response["job"]["id"], timeout_seconds=240)
    files = (job.get("result") or {}).get("files") or {}
    preview = files.get("preview")
    if job.get("status") != "done" or not preview:
        raise RuntimeError(f"Render job did not produce an output map: {job.get('error') or job}")
    return {
        "summary": f"Rendered map output {preview}.",
        "job_id": job["id"],
        "files": files,
    }


def _tool_check_map_output(
    map_spec: Dict[str, Any],
    prepare_result: Dict[str, Any],
    render_result: Dict[str, Any],
) -> Dict[str, Any]:
    checks = [
        {
            "name": "study_area_bbox_valid",
            "status": "passed" if _valid_bbox(map_spec["study_area"]["bbox"]) else "failed",
        },
        {
            "name": "prepared_dataset_path_present",
            "status": "passed" if prepare_result["dataset"].get("path") else "failed",
        },
        {
            "name": "render_output_present",
            "status": "passed" if render_result["files"].get("preview") else "failed",
        },
        {
            "name": "requested_export_format",
            "status": "passed",
            "value": map_spec["output"]["format"],
        },
    ]
    failed = [check for check in checks if check["status"] == "failed"]
    if failed:
        raise RuntimeError(f"Map QA failed: {failed}")
    return {
        "summary": "Map QA checks passed.",
        "checks": checks,
    }


def _tool_run_arcpy_code(
    map_spec: Dict[str, Any],
    code: str,
    settings: Any,
    task_id: str,
) -> Dict[str, Any]:
    output = map_spec.get("output") or {}
    payload = {
        "code": code,
        "requested_by": "gyygeo-expert-agent",
        "project_name": task_id,
        "template_id": map_spec.get("template_id") or "default",
        "output_format": output.get("format") or "jpg",
        "dpi": output.get("dpi") or 300,
        "context": map_spec.get("context") or {},
        "metadata": {
            "agent_task_id": task_id,
            "agent_task_kind": "expert_arcpy_code",
        },
    }
    response = _post_json(f"{settings.carto_engine_url}/api/v1/arcpy/code", payload)
    engine_job_id = response["job"]["id"]
    job = _poll_job(settings.carto_engine_url, engine_job_id, timeout_seconds=600)
    result = job.get("result") or {}
    files = result.get("files") or {}
    preview = files.get("preview")
    if job.get("status") != "done" or not preview:
        raise RuntimeError(f"ArcPy code engine job failed: {job.get('error') or job}")
    return {
        "summary": f"Executed ArcPy code through carto-engine job {engine_job_id}.",
        "engine_job_id": engine_job_id,
        "returncode": result.get("returncode"),
        "files": files,
        "job": job,
    }


def _tool_check_expert_output(run_result: Dict[str, Any]) -> Dict[str, Any]:
    files = run_result.get("files") or {}
    preview = files.get("preview")
    checks = [
        {
            "name": "script_succeeded",
            "status": "passed" if run_result.get("returncode") == 0 else "failed",
        },
        {
            "name": "preview_output_present",
            "status": "passed" if isinstance(preview, str) and bool(preview) else "failed",
        },
    ]
    failed = [check for check in checks if check["status"] == "failed"]
    if failed:
        raise RuntimeError(f"Expert output QA failed: {failed}")
    return {
        "summary": "Expert output QA checks passed.",
        "checks": checks,
    }


def _extract_python_code(message: str) -> Optional[str]:
    fence = re.search(r"```(?:python|py)?\s*(.*?)```", message, flags=re.IGNORECASE | re.DOTALL)
    if fence:
        return fence.group(1).strip()

    stripped = message.strip()
    if "\n" in stripped and ("import arcpy" in stripped or "arcpy." in stripped):
        return stripped
    return None


def _generate_expert_arcpy_code(
    message: str,
    context: Optional[AgentPageContext],
    settings: Any,
) -> str:
    if not settings.deepseek_api_key:
        raise HTTPException(
            status_code=503,
            detail=(
                "DeepSeek API key is not configured. Expert mode needs it to generate ArcPy code, "
                "or you can paste a complete Python script directly."
            ),
        )

    context_json = json.dumps(context.model_dump() if context else {}, ensure_ascii=False, indent=2)
    knowledge_prompt = _expert_knowledge_prompt(message, settings)
    system_prompt = (
        "You are an expert ArcGIS Pro ArcPy cartographer. Generate one complete Python script, "
        "with no Markdown fences and no explanation. The server will define these variables before "
        "your code runs: APRX_PATH, OUTPUT_DIR, OUTPUT_PATH, DPI, CONTEXT. Use ArcPy to open "
        "APRX_PATH, modify the copied APRX according to the user request, save the APRX, and export "
        "the chosen layout to OUTPUT_PATH as JPEG using DPI. Prefer aprx.listLayouts()[0] and "
        "aprx.listMaps()[0] when names are unknown. The script must create OUTPUT_PATH.\n\n"
        "Use the following project knowledge as authoritative runtime guidance:\n\n"
        f"{knowledge_prompt}"
    )
    user_prompt = (
        f"User map request:\n{message}\n\n"
        f"Current web map context JSON:\n{context_json}\n\n"
        "Return only executable Python code."
    )
    response = _deepseek_chat(
        settings=settings,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.1,
    )
    code = _extract_python_code(response) or response.strip()
    if not code:
        raise HTTPException(status_code=502, detail="DeepSeek returned empty ArcPy code.")
    return code


def _expert_knowledge_prompt(message: str, settings: Any) -> str:
    knowledge_dir = Path(settings.base_dir) / "app" / "agent_knowledge"
    files = _select_expert_knowledge_files(message)
    sections = []
    for relative_path in files:
        path = knowledge_dir / relative_path
        if not path.exists():
            continue
        sections.append(
            "### "
            + relative_path.replace("\\", "/")
            + "\n\n"
            + path.read_text(encoding="utf-8").strip()
        )
    if not sections:
        return "No project knowledge files were found. Follow the injected variable contract."
    return "\n\n---\n\n".join(sections)


def _select_expert_knowledge_files(message: str) -> List[str]:
    lowered = message.lower()
    files = [
        "arcpy_runtime.md",
        "arcpy_export.md",
        "templates/default.md",
    ]

    title_patterns = (
        "标题",
        "题名",
        "图名",
        "文字",
        "文本",
        "title",
        "text",
        "label",
    )
    layout_element_patterns = (
        "指北针",
        "北箭头",
        "比例尺",
        "图例",
        "north arrow",
        "scale bar",
        "legend",
        "map surround",
    )

    if any(pattern in message or pattern in lowered for pattern in title_patterns):
        files.extend(
            [
                "arcpy_layout_text.md",
                "examples/add_title.py",
            ]
        )
    if any(pattern in message or pattern in lowered for pattern in layout_element_patterns):
        files.extend(
            [
                "arcpy_layout_elements.md",
                "examples/move_north_arrow.py",
            ]
        )

    files.append("examples/export_jpg.py")
    return _dedupe_strings(files)


def _dedupe_strings(values: List[str]) -> List[str]:
    seen = set()
    result = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def _deepseek_chat(
    *,
    settings: Any,
    messages: List[Dict[str, str]],
    temperature: float,
) -> str:
    request_body = json.dumps(
        {
            "model": settings.deepseek_model,
            "messages": messages,
            "temperature": temperature,
            "stream": False,
        }
    ).encode("utf-8")
    upstream_request = urllib.request.Request(
        f"{settings.deepseek_base_url}/chat/completions",
        data=request_body,
        method="POST",
        headers={
            "Authorization": f"Bearer {settings.deepseek_api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "gyygeo-carto-web-api/0.1.0",
        },
    )

    try:
        with urllib.request.urlopen(
            upstream_request,
            timeout=settings.deepseek_timeout_seconds,
        ) as response:
            upstream_payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise HTTPException(status_code=exc.code, detail=detail) from exc
    except urllib.error.URLError as exc:
        raise HTTPException(status_code=502, detail=f"DeepSeek request failed: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=502, detail="DeepSeek returned invalid JSON.") from exc

    try:
        content = upstream_payload["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise HTTPException(status_code=502, detail="DeepSeek response did not include a message.") from exc

    if not isinstance(content, str) or not content.strip():
        raise HTTPException(status_code=502, detail="DeepSeek response message was empty.")
    return content.strip()


def _poll_job(base_url: str, job_id: str, *, timeout_seconds: int) -> Dict[str, Any]:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        job = _get_json(f"{base_url}/api/v1/jobs/{job_id}")
        if job.get("status") in {"done", "failed"}:
            return job
        time.sleep(2)
    raise TimeoutError(f"Timed out waiting for job {job_id}.")


def _post_json(url: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={"Content-Type": "application/json", "Accept": "application/json"},
    )
    return _open_json(req)


def _get_json(url: str) -> Dict[str, Any]:
    req = urllib.request.Request(url, method="GET", headers={"Accept": "application/json"})
    return _open_json(req)


def _open_json(req: urllib.request.Request) -> Dict[str, Any]:
    try:
        with urllib.request.urlopen(req, timeout=60) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"{req.full_url} failed with HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"{req.full_url} failed: {exc}") from exc


def _find_step(task: AgentTask, name: str) -> AgentStep:
    for step in task.steps:
        if step.name == name:
            return step
    raise KeyError(f"Unknown task step: {name}")


def _set_task_status(task: AgentTask, status: TaskStatus, message: str) -> None:
    task.status = status
    task.message = message
    task.updated_at = _now()
    _save_task(task)


def _save_task(task: AgentTask) -> None:
    with _tasks_lock:
        _tasks[task.id] = task.model_copy(deep=True)


def _get_task(task_id: str) -> Optional[AgentTask]:
    with _tasks_lock:
        task = _tasks.get(task_id)
        return task.model_copy(deep=True) if task else None


def _require_task(task_id: str) -> AgentTask:
    task = _get_task(task_id)
    if task is None:
        raise KeyError(f"Agent task not found: {task_id}")
    return task


def _valid_bbox(bbox: List[float]) -> bool:
    if len(bbox) != 4:
        return False
    xmin, ymin, xmax, ymax = bbox
    return (
        all(isinstance(value, (int, float)) for value in bbox)
        and -180 <= xmin < xmax <= 180
        and -90 <= ymin < ymax <= 90
    )


def _bbox_geometry(bbox: List[float]) -> Dict[str, Any]:
    xmin, ymin, xmax, ymax = bbox
    return {
        "type": "Polygon",
        "coordinates": [
            [
                [xmin, ymin],
                [xmax, ymin],
                [xmax, ymax],
                [xmin, ymax],
                [xmin, ymin],
            ]
        ],
    }


def _extract_output_format(message: str) -> str:
    lowered = message.lower()
    if "pdf" in lowered:
        return "pdf"
    if "jpg" in lowered or "jpeg" in lowered:
        return "jpg"
    return "png"


def _extract_layout_page(message: str) -> Dict[str, Any]:
    page_size = _extract_page_size(message)
    orientation = _extract_page_orientation(message)
    if page_size is None and orientation is None:
        return {}

    page: Dict[str, Any] = {}
    if page_size is not None:
        page["size"] = page_size
    if orientation is not None:
        page["orientation"] = orientation
    return page


def _extract_page_size(message: str) -> Optional[PageSizeName]:
    match = re.search(r"(?i)(a[0-4]|letter|legal)", message)
    if not match:
        return None
    return match.group(1).lower()  # type: ignore[return-value]


def _extract_page_orientation(message: str) -> Optional[PageOrientation]:
    lowered = message.lower()
    landscape_patterns = (
        "\u6a2a\u7248",
        "\u6a2a\u5411",
        "landscape",
        "horizontal",
    )
    portrait_patterns = (
        "\u7ad6\u7248",
        "\u7eb5\u5411",
        "portrait",
        "vertical",
    )
    if any(pattern in message or pattern in lowered for pattern in landscape_patterns):
        return "landscape"
    if any(pattern in message or pattern in lowered for pattern in portrait_patterns):
        return "portrait"
    return None


def _extract_layout_elements(message: str) -> List[Dict[str, Any]]:
    if "指北针" not in message and "north arrow" not in message.lower():
        return []

    anchor = _extract_layout_anchor(message)
    if anchor is None:
        return []

    inset = _extract_layout_element_inset(message)
    offset_x, offset_y = _inset_offsets(anchor, inset)
    return [
        {
            "element_name": _NORTH_ARROW_ELEMENT_NAME,
            "anchor": anchor,
            "offset_x": offset_x,
            "offset_y": offset_y,
        }
    ]


def _extract_layout_anchor(message: str) -> Optional[LayoutAnchor]:
    lowered = message.lower()
    for anchor, patterns in _ANCHOR_PATTERNS:
        if any(pattern in message or pattern in lowered for pattern in patterns):
            return anchor
    return None


def _extract_layout_element_inset(message: str) -> float:
    patterns = [
        r"(?:距离边缘|离边缘|边距|缩进|间距|偏移)\s*([0-9]+(?:\.[0-9]+)?)",
        r"([0-9]+(?:\.[0-9]+)?)\s*(?:的)?(?:边距|缩进|间距)",
    ]
    for pattern in patterns:
        match = re.search(pattern, message)
        if match:
            return float(match.group(1))
    return _DEFAULT_LAYOUT_ELEMENT_INSET


def _inset_offsets(anchor: LayoutAnchor, inset: float) -> tuple[float, float]:
    if anchor.endswith("_left"):
        offset_x = inset
    elif anchor.endswith("_right"):
        offset_x = -inset
    else:
        offset_x = 0.0

    if anchor.startswith("bottom_"):
        offset_y = inset
    elif anchor.startswith("top_"):
        offset_y = -inset
    else:
        offset_y = 0.0

    return offset_x, offset_y


def _extract_study_area_name(message: str) -> Optional[str]:
    match = re.search(r"\u505a\u4e00\u5f20(.+?)\u7814\u7a76\u533a", message)
    if match:
        return match.group(1).strip()
    match = re.search(r"(.+?)\u7814\u7a76\u533a\u793a\u610f\u56fe", message)
    if match:
        return match.group(1).strip()
    return None


def _slug_name(value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9_-]+", "-", value).strip("-").lower()
    return slug[:80]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()

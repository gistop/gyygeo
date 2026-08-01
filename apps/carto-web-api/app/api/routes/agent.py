from __future__ import annotations

import ast
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
from langgraph.types import Command
from pydantic import BaseModel, Field

from app.agents.cartography.graph import (
    ExpertImageSelectionCallbacks,
    build_expert_image_selection_graph,
)
from app.agents.cartography.skills.data_acquisition import (
    build_pending_image_selection,
    build_search_payload,
    select_recommended_item,
    selected_item_from_search,
)
from app.agents.cartography.skills.cartographic_standards import (
    apply_cartographic_standards_to_tool_calls,
)
from app.agents.cartography.skills.remote_sensing_basemap import (
    build_prepare_payload,
    prepared_dataset_path,
)


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
_expert_image_selection_graph: Any = None
_expert_graph_settings: dict[str, Any] = {}
_expert_graph_settings_lock = threading.Lock()

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
_EXPERT_TOOL_RUN_ARCPY_CODE = "run_arcpy_code"
_EXPERT_TOOL_SEARCH_REMOTE_SENSING_IMAGES = "search_remote_sensing_images"
_EXPERT_TOOL_PREPARE_REMOTE_SENSING_BASEMAP = "prepare_remote_sensing_basemap"
_EXPERT_TOOL_SCHEMAS: List[Dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": _EXPERT_TOOL_SEARCH_REMOTE_SENSING_IMAGES,
            "description": (
                "Search remote-sensing imagery through the internal data-service using the "
                "current AOI and optional search filters."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "provider": {"type": "string", "default": "mpc"},
                    "collection": {"type": "string"},
                    "bbox": {
                        "type": "array",
                        "items": {"type": "number"},
                        "minItems": 4,
                        "maxItems": 4,
                    },
                    "datetime": {"type": "string"},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 100, "default": 10},
                    "cloud_cover_lte": {"type": "number"},
                },
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": _EXPERT_TOOL_PREPARE_REMOTE_SENSING_BASEMAP,
            "description": (
                "Prepare a local cartography-ready raster through the internal data-service. "
                "Use after search_remote_sensing_images unless an item_id is already known."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "item_id": {"type": "string"},
                    "bands": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                    "target_resolution": {"type": "number"},
                    "target_crs": {"type": "string"},
                },
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": _EXPERT_TOOL_RUN_ARCPY_CODE,
            "description": (
                "Run a complete ArcPy cartography script through the internal carto-engine."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "code": {
                        "type": "string",
                        "description": (
                            "Complete executable Python code. The runtime injects APRX_PATH, "
                            "OUTPUT_DIR, OUTPUT_PATH, DPI, and CONTEXT."
                        ),
                    },
                    "output_format": {
                        "type": "string",
                        "enum": ["jpg", "png", "pdf"],
                        "default": "jpg",
                    },
                    "dpi": {
                        "type": "integer",
                        "minimum": 72,
                        "maximum": 600,
                        "default": 300,
                    },
                    "template_id": {
                        "type": "string",
                        "default": "default",
                    },
                    "text_styles": {
                        "type": "array",
                        "description": (
                            "Optional structured text typography operations executed by "
                            "carto-engine after the generated ArcPy code. Use for stable "
                            "font family, font size, and font style changes."
                        ),
                        "items": {
                            "type": "object",
                            "properties": {
                                "element_name": {"type": "string"},
                                "font_family": {"type": "string"},
                                "font_size": {"type": "number"},
                                "font_style": {"type": "string"},
                                "required": {"type": "boolean", "default": True},
                            },
                            "required": ["element_name"],
                            "additionalProperties": False,
                        },
                    },
                },
                "required": ["code"],
                "additionalProperties": False,
            },
        },
    }
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
    prepared_dataset_path: Optional[str] = None


class AgentChatRequest(BaseModel):
    messages: List[AgentChatMessage] = Field(min_length=1, max_length=30)
    context: Optional[AgentPageContext] = None


class AgentImageSelectionRequest(BaseModel):
    item_id: str = Field(min_length=1, max_length=500)


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
                "I am using the current map AOI as the study-area boundary and will "
                "produce a jpg output."
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
    tool_calls = _expert_tool_calls_from_user_message(user_message, payload.context, settings)

    task = _create_expert_task(user_message, payload.context, tool_calls)
    if _expert_tool_calls_need_image_selection(tool_calls):
        _executor.submit(_run_expert_image_selection_task, task.id, settings)
        content = (
            f"Started expert image search task {task.id}. "
            "I will pause after searching so you can select one candidate image on the left."
        )
    else:
        _executor.submit(_run_expert_tool_call_task, task.id, settings)
        content = (
            f"Started expert tool task {task.id}. "
            f"I am executing {len(tool_calls)} internal tool step(s)."
        )

    return AgentChatResponse(
        message=AgentChatMessage(
            role="assistant",
            content=content,
        ),
        model="gyygeo-expert-tools-0.1",
        task=task,
    )


@router.get("/tasks/{task_id}", response_model=AgentTask)
def get_task(task_id: str) -> AgentTask:
    task = _get_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Agent task not found.")
    return task


@router.post("/tasks/{task_id}/select-image", response_model=AgentTask)
def select_task_image(
    request: Request,
    task_id: str,
    payload: AgentImageSelectionRequest,
) -> AgentTask:
    task = _get_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Agent task not found.")
    if task.status != "waiting_for_user" or not _task_waits_for_image_selection(task):
        raise HTTPException(status_code=409, detail="Agent task is not waiting for image selection.")

    settings = request.app.state.settings
    _executor.submit(_resume_expert_image_selection_task, task.id, payload.item_id, settings)
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
    tool_call: Dict[str, Any] | List[Dict[str, Any]],
) -> AgentTask:
    now = _now()
    task_id = "expert_" + uuid4().hex
    tool_calls = _normalize_expert_tool_calls(tool_call)
    run_tool_call = _find_expert_tool_call(tool_calls, _EXPERT_TOOL_RUN_ARCPY_CODE)
    run_arguments = run_tool_call["arguments"] if run_tool_call else {}
    template_id = str(run_arguments.get("template_id") or "default")
    output_format = str(run_arguments.get("output_format") or "jpg")
    dpi = int(run_arguments.get("dpi") or 300)
    map_spec = _create_expert_map_spec(
        context,
        tool_calls,
        template_id=template_id,
        output_format=output_format,
        dpi=dpi,
    )
    steps = [
        AgentStep(
            name=call["name"],
            input={
                "tool_name": call["name"],
                "arguments": _redact_expert_tool_arguments(call["arguments"]),
            },
        )
        for call in tool_calls
    ]
    if _expert_tool_calls_need_image_selection(tool_calls):
        search_index = next(
            (
                index
                for index, call in enumerate(tool_calls)
                if call["name"] == _EXPERT_TOOL_SEARCH_REMOTE_SENSING_IMAGES
            ),
            -1,
        )
        steps.insert(search_index + 1, AgentStep(name="select_remote_sensing_image"))
    if run_tool_call:
        steps.append(AgentStep(name="check_expert_output"))
    task = AgentTask(
        id=task_id,
        kind="expert_tool_call",
        status="queued",
        created_at=now,
        updated_at=now,
        message="Expert internal tool task queued.",
        map_spec=map_spec,
        steps=steps,
        outputs={"tool_calls": tool_calls},
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


def _run_expert_tool_call_task(task_id: str, settings: Any) -> None:
    task = _require_task(task_id)
    try:
        _set_task_status(task, "running", "Running expert internal tool.")
        tool_calls = task.outputs["tool_calls"]
        run_result = None
        for tool_call in tool_calls:
            result = _run_step(
                task,
                str(tool_call["name"]),
                lambda call=tool_call: _execute_expert_tool_call(task, call, settings),
            )
            _merge_task_outputs(task, _expert_tool_output(tool_call["name"], result))
            if tool_call["name"] == _EXPERT_TOOL_RUN_ARCPY_CODE:
                run_result = result

        if run_result is not None:
            check_result = _run_step(
                task,
                "check_expert_output",
                lambda: _tool_check_expert_output(run_result),
            )
            _merge_task_outputs(task, {"qa": check_result})
        _set_task_status(task, "done", "Expert internal tool completed.")
    except Exception as exc:  # noqa: BLE001
        task.error = str(exc)
        _set_task_status(task, "failed", f"Expert internal tool failed: {task.error}")


def _run_expert_image_selection_task(task_id: str, settings: Any) -> None:
    _remember_expert_graph_settings(task_id, settings)
    try:
        result = _expert_image_selection_graph_instance().invoke(
            {"task_id": task_id},
            config=_expert_graph_config(task_id),
        )
        if "__interrupt__" in result:
            task = _require_task(task_id)
            _mark_task_waiting_for_image_selection(task)
    except Exception as exc:  # noqa: BLE001
        task = _require_task(task_id)
        task.error = str(exc)
        _set_task_status(task, "failed", f"Expert image-selection workflow failed: {task.error}")


def _resume_expert_image_selection_task(
    task_id: str,
    item_id: str,
    settings: Any,
) -> None:
    _remember_expert_graph_settings(task_id, settings)
    try:
        _expert_image_selection_graph_instance().invoke(
            Command(resume={"item_id": item_id}),
            config=_expert_graph_config(task_id),
        )
    except Exception as exc:  # noqa: BLE001
        task = _require_task(task_id)
        task.error = str(exc)
        _set_task_status(task, "failed", f"Expert image-selection workflow failed: {task.error}")


def _expert_graph_search_images(task_id: str) -> None:
    task = _require_task(task_id)
    settings = _expert_graph_settings_for_task(task_id)
    _set_task_status(task, "running", "Searching remote-sensing candidate images.")
    tool_call = _require_expert_tool_call(task, _EXPERT_TOOL_SEARCH_REMOTE_SENSING_IMAGES)
    search_result = _run_step(
        task,
        _EXPERT_TOOL_SEARCH_REMOTE_SENSING_IMAGES,
        lambda: _execute_expert_tool_call(task, tool_call, settings),
    )
    recommended_item = _tool_select_best_image(search_result)
    _merge_task_outputs(
        task,
        {
            "search": search_result,
            "recommended_item": recommended_item,
            "pending_action": build_pending_image_selection(recommended_item),
        },
    )


def _expert_graph_continue_with_image(task_id: str, item_id: str) -> None:
    task = _require_task(task_id)
    settings = _expert_graph_settings_for_task(task_id)
    selected_item = _selected_item_from_search(task, item_id)
    _complete_image_selection_step(task, selected_item)
    _merge_task_outputs(
        task,
        {
            "selected_item": selected_item,
            "pending_action": None,
        },
    )
    _set_task_status(task, "running", f"Continuing expert map task with image {item_id}.")

    run_result = None
    for tool_call in task.outputs["tool_calls"]:
        if tool_call["name"] == _EXPERT_TOOL_SEARCH_REMOTE_SENSING_IMAGES:
            continue
        next_call = _tool_call_with_selected_item(tool_call, item_id)
        result = _run_step(
            task,
            str(next_call["name"]),
            lambda call=next_call: _execute_expert_tool_call(task, call, settings),
        )
        _merge_task_outputs(task, _expert_tool_output(next_call["name"], result))
        if next_call["name"] == _EXPERT_TOOL_RUN_ARCPY_CODE:
            run_result = result

    if run_result is not None:
        check_result = _run_step(
            task,
            "check_expert_output",
            lambda: _tool_check_expert_output(run_result),
        )
        _merge_task_outputs(task, {"qa": check_result})
    _set_task_status(task, "done", "Expert map task completed with the selected image.")
    _forget_expert_graph_settings(task_id)


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


def _expert_image_selection_graph_instance() -> Any:
    global _expert_image_selection_graph
    if _expert_image_selection_graph is None:
        _expert_image_selection_graph = build_expert_image_selection_graph(
            ExpertImageSelectionCallbacks(
                search_images=_expert_graph_search_images,
                continue_with_image=_expert_graph_continue_with_image,
            )
        )
    return _expert_image_selection_graph


def _expert_graph_config(task_id: str) -> Dict[str, Any]:
    return {"configurable": {"thread_id": task_id}}


def _remember_expert_graph_settings(task_id: str, settings: Any) -> None:
    with _expert_graph_settings_lock:
        _expert_graph_settings[task_id] = settings


def _expert_graph_settings_for_task(task_id: str) -> Any:
    with _expert_graph_settings_lock:
        settings = _expert_graph_settings.get(task_id)
    if settings is None:
        raise RuntimeError(f"Expert graph settings were not registered for task {task_id}.")
    return settings


def _forget_expert_graph_settings(task_id: str) -> None:
    with _expert_graph_settings_lock:
        _expert_graph_settings.pop(task_id, None)


def _mark_task_waiting_for_image_selection(task: AgentTask) -> None:
    pending_action = task.outputs.get("pending_action")
    if not isinstance(pending_action, dict):
        pending_action = {"type": "select_image"}
        task.outputs = {**task.outputs, "pending_action": pending_action}
    step = _find_step(task, "select_remote_sensing_image")
    step.status = "running"
    step.started_at = step.started_at or _now()
    step.summary = "Waiting for the user to select one candidate image."
    task.status = "waiting_for_user"
    task.message = (
        "Found candidate remote-sensing images. Select one image from the left search "
        "results to continue preparing the basemap."
    )
    task.updated_at = _now()
    _save_task(task)


def _complete_image_selection_step(
    task: AgentTask,
    selected_item: Dict[str, Any],
) -> None:
    step = _find_step(task, "select_remote_sensing_image")
    step.status = "done"
    step.finished_at = _now()
    step.output = selected_item
    step.summary = selected_item.get("summary", "")
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
    payload = build_search_payload(map_spec)
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
    return select_recommended_item(items)


def _tool_prepare_remote_sensing_basemap(
    map_spec: Dict[str, Any],
    selected_item: Dict[str, Any],
    data_service_url: str,
) -> Dict[str, Any]:
    payload = build_prepare_payload(map_spec, selected_item)
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
    geometry = map_spec["study_area"].get("geometry") or _bbox_geometry(
        map_spec["study_area"]["bbox"]
    )
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


def _execute_expert_tool_call(
    task: AgentTask,
    tool_call: Dict[str, Any],
    settings: Any,
) -> Dict[str, Any]:
    normalized = _normalize_expert_tool_call(tool_call)
    if normalized["name"] == _EXPERT_TOOL_SEARCH_REMOTE_SENSING_IMAGES:
        map_spec = _expert_map_spec_with_arguments(task.map_spec, normalized["arguments"])
        _tool_validate_map_spec(map_spec)
        return _tool_search_remote_sensing_images(map_spec, settings.data_service_url)

    if normalized["name"] == _EXPERT_TOOL_PREPARE_REMOTE_SENSING_BASEMAP:
        map_spec = _expert_map_spec_with_arguments(task.map_spec, normalized["arguments"])
        _tool_validate_map_spec(map_spec)
        selected_item = _expert_selected_item_for_prepare(task, normalized["arguments"])
        result = _tool_prepare_remote_sensing_basemap(
            map_spec,
            selected_item,
            settings.data_service_url,
        )
        _apply_prepared_dataset_to_expert_context(task, result)
        return result

    if normalized["name"] == _EXPERT_TOOL_RUN_ARCPY_CODE:
        return _tool_run_arcpy_code(
            task.map_spec,
            normalized["arguments"]["code"],
            settings,
            task.id,
            text_styles=normalized["arguments"].get("text_styles") or [],
        )
    raise ValueError(f"Unknown expert tool: {normalized['name']}")


def _expert_tool_output(tool_name: str, result: Dict[str, Any]) -> Dict[str, Any]:
    if tool_name == _EXPERT_TOOL_SEARCH_REMOTE_SENSING_IMAGES:
        return {"search": result}
    if tool_name == _EXPERT_TOOL_PREPARE_REMOTE_SENSING_BASEMAP:
        return {"prepared_dataset": result}
    if tool_name == _EXPERT_TOOL_RUN_ARCPY_CODE:
        return {"run": result}
    return {tool_name: result}


def _expert_selected_item_for_prepare(
    task: AgentTask,
    arguments: Dict[str, Any],
) -> Dict[str, Any]:
    item_id = arguments.get("item_id")
    if isinstance(item_id, str) and item_id.strip():
        return {
            "summary": f"Using requested image {item_id}.",
            "item": {"item_id": item_id.strip()},
        }

    search_result = task.outputs.get("search")
    if not isinstance(search_result, dict):
        raise RuntimeError(
            "prepare_remote_sensing_basemap needs a prior search_remote_sensing_images result "
            "or an explicit item_id."
        )
    selected_item = _tool_select_best_image(search_result)
    _merge_task_outputs(task, {"selected_item": selected_item})
    return selected_item


def _apply_prepared_dataset_to_expert_context(
    task: AgentTask,
    prepare_result: Dict[str, Any],
) -> None:
    path = prepared_dataset_path(prepare_result)
    if path is None:
        return

    context = task.map_spec.get("context")
    if not isinstance(context, dict):
        context = {}
    context = {**context, "prepared_dataset_path": path}
    task.map_spec = {**task.map_spec, "context": context}
    task.updated_at = _now()
    _save_task(task)


def _tool_run_arcpy_code(
    map_spec: Dict[str, Any],
    code: str,
    settings: Any,
    task_id: str,
    *,
    text_styles: List[Dict[str, Any]],
) -> Dict[str, Any]:
    output = map_spec.get("output") or {}
    code = _ensure_prepared_dataset_loaded(code, map_spec)
    payload = {
        "code": code,
        "requested_by": "gyygeo-expert-agent",
        "project_name": task_id,
        "template_id": map_spec.get("template_id") or "default",
        "output_format": output.get("format") or "jpg",
        "dpi": output.get("dpi") or 300,
        "text_styles": text_styles,
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


def _expert_tool_calls_from_user_message(
    message: str,
    context: Optional[AgentPageContext],
    settings: Any,
) -> List[Dict[str, Any]]:
    code = _extract_python_code(message)
    if code is not None:
        return _apply_cartographic_standards_to_expert_tool_calls(
            message,
            [
                _create_run_arcpy_code_tool_call(
                    code,
                    output_format=_extract_expert_output_format(message),
                )
            ],
        )
    return _generate_expert_tool_calls(message, context, settings)


def _create_run_arcpy_code_tool_call(
    code: str,
    *,
    output_format: str = "jpg",
    dpi: int = 300,
    template_id: str = "default",
    text_styles: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    arguments: Dict[str, Any] = {
        "code": code,
        "output_format": output_format,
        "dpi": dpi,
        "template_id": template_id,
    }
    if text_styles:
        arguments["text_styles"] = text_styles
    return _normalize_expert_tool_call(
        {
            "name": _EXPERT_TOOL_RUN_ARCPY_CODE,
            "arguments": arguments,
        }
    )


def _normalize_expert_tool_calls(
    value: Dict[str, Any] | List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    if isinstance(value, list):
        raw_calls = value
    elif isinstance(value, dict):
        raw_calls = (
            value.get("tool_calls")
            if isinstance(value.get("tool_calls"), list)
            else [value]
        )
    else:
        raise ValueError("Expert tool call payload must be an object or list.")

    calls = [_normalize_expert_tool_call(call) for call in raw_calls]
    if not calls:
        raise ValueError("Expert tool call payload cannot be empty.")
    return calls


def _normalize_expert_tool_call(tool_call: Dict[str, Any]) -> Dict[str, Any]:
    raw = tool_call
    nested = raw.get("tool_call")
    if isinstance(nested, dict):
        raw = nested

    name = raw.get("name") or raw.get("tool")
    function = raw.get("function")
    if isinstance(function, dict):
        name = name or function.get("name")

    if "arguments" in raw:
        arguments = raw.get("arguments")
    elif "input" in raw:
        arguments = raw.get("input")
    else:
        arguments = None
    if arguments is None and isinstance(function, dict):
        arguments = function.get("arguments")
    if isinstance(arguments, str):
        try:
            arguments = json.loads(arguments)
        except json.JSONDecodeError as exc:
            raise ValueError("Expert tool arguments were not valid JSON.") from exc
    if not isinstance(arguments, dict):
        raise ValueError("Expert tool call must include object arguments.")

    if name == _EXPERT_TOOL_SEARCH_REMOTE_SENSING_IMAGES:
        return {
            "name": _EXPERT_TOOL_SEARCH_REMOTE_SENSING_IMAGES,
            "arguments": _normalize_expert_search_arguments(arguments),
        }

    if name == _EXPERT_TOOL_PREPARE_REMOTE_SENSING_BASEMAP:
        return {
            "name": _EXPERT_TOOL_PREPARE_REMOTE_SENSING_BASEMAP,
            "arguments": _normalize_expert_prepare_arguments(arguments),
        }

    if name != _EXPERT_TOOL_RUN_ARCPY_CODE:
        raise ValueError(f"Unsupported expert tool: {name}")

    return _normalize_expert_run_arcpy_arguments(arguments)


def _normalize_expert_search_arguments(arguments: Dict[str, Any]) -> Dict[str, Any]:
    normalized: Dict[str, Any] = {}
    for key in ("provider", "collection", "datetime"):
        value = arguments.get(key)
        if isinstance(value, str) and value.strip():
            normalized[key] = value.strip()

    bbox = arguments.get("bbox")
    if bbox is not None:
        if not isinstance(bbox, list) or len(bbox) != 4:
            raise ValueError("search_remote_sensing_images bbox must have four numbers.")
        normalized["bbox"] = [float(value) for value in bbox]

    limit = arguments.get("limit")
    if limit is not None:
        try:
            limit_value = int(limit)
        except (TypeError, ValueError) as exc:
            raise ValueError("search_remote_sensing_images limit must be an integer.") from exc
        if limit_value < 1 or limit_value > 100:
            raise ValueError("search_remote_sensing_images limit must be between 1 and 100.")
        normalized["limit"] = limit_value

    cloud_cover_lte = arguments.get("cloud_cover_lte")
    if cloud_cover_lte is not None:
        try:
            normalized["cloud_cover_lte"] = float(cloud_cover_lte)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                "search_remote_sensing_images cloud_cover_lte must be numeric."
            ) from exc
    return normalized


def _normalize_expert_prepare_arguments(arguments: Dict[str, Any]) -> Dict[str, Any]:
    normalized: Dict[str, Any] = {}
    item_id = arguments.get("item_id")
    if isinstance(item_id, str) and item_id.strip():
        normalized["item_id"] = item_id.strip()

    bands = arguments.get("bands")
    if bands is not None:
        if not isinstance(bands, list) or not bands:
            raise ValueError("prepare_remote_sensing_basemap bands must be a non-empty list.")
        normalized["bands"] = [str(value).strip() for value in bands if str(value).strip()]
        if not normalized["bands"]:
            raise ValueError("prepare_remote_sensing_basemap bands must include a band name.")

    target_resolution = arguments.get("target_resolution")
    if target_resolution is not None:
        try:
            normalized["target_resolution"] = float(target_resolution)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                "prepare_remote_sensing_basemap target_resolution must be numeric."
            ) from exc

    target_crs = arguments.get("target_crs")
    if isinstance(target_crs, str) and target_crs.strip():
        normalized["target_crs"] = target_crs.strip()
    return normalized


def _normalize_expert_run_arcpy_arguments(arguments: Dict[str, Any]) -> Dict[str, Any]:
    code = arguments.get("code")
    if not isinstance(code, str) or not code.strip():
        raise ValueError("run_arcpy_code requires non-empty code.")

    output_format = str(arguments.get("output_format") or arguments.get("format") or "jpg").lower()
    if output_format == "jpeg":
        output_format = "jpg"
    if output_format not in {"jpg", "png", "pdf"}:
        raise ValueError(f"Unsupported expert output format: {output_format}")

    try:
        dpi = int(arguments.get("dpi") or 300)
    except (TypeError, ValueError) as exc:
        raise ValueError("Expert tool dpi must be an integer.") from exc
    if dpi < 72 or dpi > 600:
        raise ValueError("Expert tool dpi must be between 72 and 600.")

    template_id = str(arguments.get("template_id") or "default").strip()
    if not template_id:
        raise ValueError("Expert tool template_id cannot be empty.")

    normalized_arguments: Dict[str, Any] = {
        "code": _repair_generated_arcpy_code(code.strip()),
        "output_format": output_format,
        "dpi": dpi,
        "template_id": template_id,
    }
    text_styles = _normalize_text_styles(arguments.get("text_styles"))
    if text_styles:
        normalized_arguments["text_styles"] = text_styles

    return {
        "name": _EXPERT_TOOL_RUN_ARCPY_CODE,
        "arguments": normalized_arguments,
    }


def _normalize_text_styles(value: Any) -> List[Dict[str, Any]]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError("run_arcpy_code text_styles must be a list.")

    styles = []
    for item in value:
        if not isinstance(item, dict):
            raise ValueError("Each run_arcpy_code text style must be an object.")
        element_name = item.get("element_name")
        if not isinstance(element_name, str) or not element_name.strip():
            raise ValueError("Each run_arcpy_code text style requires element_name.")
        style: Dict[str, Any] = {"element_name": element_name.strip()}

        font_family = item.get("font_family")
        if isinstance(font_family, str) and font_family.strip():
            style["font_family"] = font_family.strip()

        font_style = item.get("font_style")
        if isinstance(font_style, str) and font_style.strip():
            style["font_style"] = font_style.strip()

        font_size = item.get("font_size")
        if font_size is not None:
            try:
                font_size_value = float(font_size)
            except (TypeError, ValueError) as exc:
                raise ValueError("run_arcpy_code text style font_size must be numeric.") from exc
            if font_size_value <= 0:
                raise ValueError("run_arcpy_code text style font_size must be positive.")
            style["font_size"] = font_size_value

        required = item.get("required")
        if required is not None:
            style["required"] = bool(required)

        if not any(key in style for key in ("font_family", "font_size", "font_style")):
            raise ValueError(
                "Each run_arcpy_code text style requires font_family, font_size, or font_style."
            )
        styles.append(style)
    return styles


class _CreateTextElementRepairer(ast.NodeTransformer):
    def visit_Call(self, node: ast.Call) -> ast.AST:
        self.generic_visit(node)
        if not isinstance(node.func, ast.Attribute) or node.func.attr != "createTextElement":
            return node

        if len(node.args) >= 4 and _string_constant(node.args[1]) == "TEXT":
            point_arg = node.args[3]
            if isinstance(point_arg, ast.Tuple) and len(point_arg.elts) == 2:
                point_arg = ast.Call(
                    func=ast.Attribute(value=ast.Name(id="arcpy", ctx=ast.Load()), attr="Point", ctx=ast.Load()),
                    args=list(point_arg.elts),
                    keywords=[],
                )
            keywords = list(node.keywords)
            if not _has_keyword(keywords, "name"):
                keywords.append(ast.keyword(arg="name", value=node.args[2]))
            if not _has_keyword(keywords, "text_size"):
                keywords.append(ast.keyword(arg="text_size", value=ast.Constant(value=24)))
            node.args = [
                ast.Name(id="layout", ctx=ast.Load()),
                point_arg,
                ast.Constant(value="POINT"),
                node.args[0],
            ]
            node.keywords = keywords
            return node

        if len(node.args) >= 3 and (_string_constant(node.args[2]) or "").upper() in {
            "TEXT",
            "TITLE",
        }:
            node.args[2] = ast.Constant(value="POINT")
        return node


def _repair_generated_arcpy_code(code: str) -> str:
    repaired = _repair_title_layout_units(code)
    try:
        tree = ast.parse(repaired)
    except SyntaxError:
        return repaired
    tree = _CreateTextElementRepairer().visit(tree)
    ast.fix_missing_locations(tree)
    try:
        return ast.unparse(tree)
    except Exception:  # noqa: BLE001
        return repaired


def _repair_title_layout_units(code: str) -> str:
    return re.sub(r"(page_height\s*-\s*)28(?:\.0)?\b", r"\g<1>0.35", code)


def _string_constant(node: ast.AST) -> Optional[str]:
    return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else None


def _has_keyword(keywords: List[ast.keyword], name: str) -> bool:
    return any(keyword.arg == name for keyword in keywords)


def _ensure_prepared_dataset_loaded(code: str, map_spec: Dict[str, Any]) -> str:
    context = map_spec.get("context")
    if not isinstance(context, dict) or not context.get("prepared_dataset_path"):
        return code
    if "addDataFromPath" in code:
        return code

    block = """
map_obj = aprx.listMaps()[0]
prepared_dataset_path = CONTEXT.get("prepared_dataset_path")
if prepared_dataset_path:
    added_layer = map_obj.addDataFromPath(prepared_dataset_path)
    if hasattr(added_layer, "name"):
        added_layer.name = "Prepared Remote Sensing Basemap"

    map_frames = layout.listElements("MAPFRAME_ELEMENT")
    if map_frames:
        map_frame = map_frames[0]
        try:
            layer_extent = map_frame.getLayerExtent(added_layer, False, True)
            padding = 0.08
            x_padding = (float(layer_extent.XMax) - float(layer_extent.XMin)) * padding
            y_padding = (float(layer_extent.YMax) - float(layer_extent.YMin)) * padding
            padded_extent = arcpy.Extent(
                float(layer_extent.XMin) - x_padding,
                float(layer_extent.YMin) - y_padding,
                float(layer_extent.XMax) + x_padding,
                float(layer_extent.YMax) + y_padding,
            )
            if getattr(layer_extent, "spatialReference", None):
                try:
                    padded_extent.spatialReference = layer_extent.spatialReference
                except Exception:
                    pass
            map_frame.camera.setExtent(padded_extent)
        except Exception:
            pass
""".strip()
    layout_match = re.search(
        r"(?m)^(?P<indent>\s*)layout\s*=\s*aprx\.listLayouts\(\)\[0\]\s*$",
        code,
    )
    if not layout_match:
        return code
    insert_at = layout_match.end()
    return f"{code[:insert_at]}\n\n{block}\n{code[insert_at:]}"


def _create_expert_map_spec(
    context: Optional[AgentPageContext],
    tool_calls: List[Dict[str, Any]],
    *,
    template_id: str,
    output_format: str,
    dpi: int,
) -> Dict[str, Any]:
    context_dict = context.model_dump() if context else {}
    bbox = context.bbox if context else []
    geometry = context.geometry.model_dump() if context and context.geometry else None
    basemap = {
        "provider": context.provider if context else "mpc",
        "collection": context.collection if context else "",
        "datetime": context.datetime if context else None,
        "cloud_cover_lte": context.cloud_cover_lte if context else None,
        "limit": context.limit if context else 10,
        "bands": context.bands if context else ["red", "green", "blue"],
        "target_resolution": context.target_resolution if context else None,
        "target_crs": context.target_crs if context else None,
    }
    map_spec = {
        "schema_version": "0.1",
        "map_kind": "expert_tool_call",
        "template_id": template_id,
        "context": context_dict,
        "study_area": {
            "name": context.map_title if context else None,
            "bbox": bbox,
            "geometry": geometry,
        },
        "basemap": basemap,
        "output": {
            "format": output_format,
            "dpi": dpi,
        },
        "tool_calls": [
            {
                "name": call["name"],
                "arguments": _redact_expert_tool_arguments(call["arguments"]),
            }
            for call in tool_calls
        ],
    }
    for call in tool_calls:
        if call["name"] in {
            _EXPERT_TOOL_SEARCH_REMOTE_SENSING_IMAGES,
            _EXPERT_TOOL_PREPARE_REMOTE_SENSING_BASEMAP,
        }:
            map_spec = _expert_map_spec_with_arguments(map_spec, call["arguments"])
    return map_spec


def _expert_map_spec_with_arguments(
    map_spec: Dict[str, Any],
    arguments: Dict[str, Any],
) -> Dict[str, Any]:
    next_spec = {
        **map_spec,
        "study_area": {**(map_spec.get("study_area") or {})},
        "basemap": {**(map_spec.get("basemap") or {})},
    }
    if "bbox" in arguments:
        next_spec["study_area"]["bbox"] = arguments["bbox"]
    for key in ("provider", "collection", "datetime", "limit", "cloud_cover_lte"):
        if key in arguments:
            next_spec["basemap"][key] = arguments[key]
    for key in ("bands", "target_resolution", "target_crs"):
        if key in arguments:
            next_spec["basemap"][key] = arguments[key]
    return next_spec


def _find_expert_tool_call(
    tool_calls: List[Dict[str, Any]],
    name: str,
) -> Optional[Dict[str, Any]]:
    for call in tool_calls:
        if call["name"] == name:
            return call
    return None


def _expert_tool_calls_need_image_selection(tool_calls: List[Dict[str, Any]]) -> bool:
    names = _expert_tool_names(tool_calls)
    return (
        _EXPERT_TOOL_SEARCH_REMOTE_SENSING_IMAGES in names
        and _EXPERT_TOOL_PREPARE_REMOTE_SENSING_BASEMAP in names
    )


def _task_waits_for_image_selection(task: AgentTask) -> bool:
    pending_action = task.outputs.get("pending_action")
    return isinstance(pending_action, dict) and pending_action.get("type") == "select_image"


def _require_expert_tool_call(task: AgentTask, name: str) -> Dict[str, Any]:
    tool_calls = task.outputs.get("tool_calls")
    if not isinstance(tool_calls, list):
        raise RuntimeError("Expert task does not include tool calls.")
    call = _find_expert_tool_call(tool_calls, name)
    if call is None:
        raise RuntimeError(f"Expert task does not include {name}.")
    return call


def _selected_item_from_search(task: AgentTask, item_id: str) -> Dict[str, Any]:
    search_result = task.outputs.get("search")
    if not isinstance(search_result, dict):
        raise RuntimeError("Expert task has no search result to select from.")
    return selected_item_from_search(search_result, item_id)


def _tool_call_with_selected_item(
    tool_call: Dict[str, Any],
    item_id: str,
) -> Dict[str, Any]:
    if tool_call["name"] != _EXPERT_TOOL_PREPARE_REMOTE_SENSING_BASEMAP:
        return tool_call
    return {
        **tool_call,
        "arguments": {
            **tool_call["arguments"],
            "item_id": item_id,
        },
    }


def _redact_expert_tool_arguments(arguments: Dict[str, Any]) -> Dict[str, Any]:
    redacted = dict(arguments)
    code = redacted.pop("code", None)
    if isinstance(code, str):
        redacted["code_preview"] = code[:2000]
        redacted["code_length"] = len(code)
    return redacted


def _generate_expert_tool_calls(
    message: str,
    context: Optional[AgentPageContext],
    settings: Any,
) -> List[Dict[str, Any]]:
    if not settings.deepseek_api_key:
        raise HTTPException(
            status_code=503,
            detail=(
                "DeepSeek API key is not configured. Expert mode needs it to generate a tool call, "
                "or you can paste a complete Python script directly."
            ),
        )

    context_json = json.dumps(context.model_dump() if context else {}, ensure_ascii=False, indent=2)
    knowledge_prompt = _expert_knowledge_prompt(message, settings)
    system_prompt = (
        "You are an expert ArcGIS Pro ArcPy cartographer in an internal agent. Use these "
        "internal tools when needed: search_remote_sensing_images, prepare_remote_sensing_basemap, "
        "and run_arcpy_code. If the user asks to make a map from remote-sensing imagery and "
        "CONTEXT has no prepared_dataset_path, call search_remote_sensing_images first, then "
        "prepare_remote_sensing_basemap, then run_arcpy_code. If CONTEXT already has "
        "prepared_dataset_path, call run_arcpy_code directly unless the user asks for new data. "
        "If the chat API supports tool calls, return the needed tool calls in order. If tool calls "
        "are unavailable, return only a JSON object with this shape: "
        '{"tool_calls":[{"name":"search_remote_sensing_images","arguments":{}},'
        '{"name":"prepare_remote_sensing_basemap","arguments":{}},'
        '{"name":"run_arcpy_code","arguments":{"code":"...","output_format":"jpg","dpi":300,'
        '"template_id":"default"}}]}. The ArcPy code must be complete Python code with no '
        "Markdown. "
        "The server will define APRX_PATH, OUTPUT_DIR, OUTPUT_PATH, DPI, and CONTEXT before the "
        "code runs. Use ArcPy to open APRX_PATH, modify the copied APRX according to the user "
        "request, save the APRX, and export the chosen layout to OUTPUT_PATH. Prefer "
        "aprx.listLayouts()[0] and aprx.listMaps()[0] when names are unknown. If CONTEXT includes "
        "prepared_dataset_path, treat it as the already-prepared local remote-sensing raster and "
        "add it to the map with map_obj.addDataFromPath unless the user explicitly asks otherwise. "
        "After adding that raster, set the layout map frame extent to the added layer extent with "
        "approximately 8 percent padding. The script must create OUTPUT_PATH.\n\n"
        "For text typography such as title font family, font size, or font style, prefer the "
        "run_arcpy_code text_styles argument instead of hand-writing ArcPy typography code. "
        "Use element_name such as Title when the target layout text element is known.\n\n"
        "Use the following project knowledge as authoritative runtime guidance:\n\n"
        f"{knowledge_prompt}"
    )
    user_prompt = (
        f"User map request:\n{message}\n\n"
        f"Current web map context JSON:\n{context_json}\n\n"
        "Create the internal tool call now."
    )
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]

    try:
        completion_message = _deepseek_chat_completion(
            settings=settings,
            messages=messages,
            temperature=0.1,
            tools=_EXPERT_TOOL_SCHEMAS,
            tool_choice="auto",
        )
        tool_calls = _parse_expert_tool_call_message(completion_message)
        return _complete_expert_tool_calls(message, context, tool_calls, settings)
    except HTTPException as exc:
        if exc.status_code not in {400, 422}:
            raise

    fallback_content = _deepseek_chat(settings=settings, messages=messages, temperature=0.1)
    try:
        tool_calls = _parse_expert_tool_call_content(fallback_content)
        return _complete_expert_tool_calls(message, context, tool_calls, settings)
    except ValueError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"DeepSeek returned invalid tool call: {exc}",
        ) from exc


def _parse_expert_tool_call_message(message: Dict[str, Any]) -> List[Dict[str, Any]]:
    tool_calls = message.get("tool_calls") or []
    parsed_calls = []
    if isinstance(tool_calls, list):
        for tool_call in tool_calls:
            if not isinstance(tool_call, dict):
                continue
            function = tool_call.get("function")
            if not isinstance(function, dict):
                continue
            parsed_calls.append(
                _normalize_expert_tool_call(
                    {
                        "name": function.get("name"),
                        "arguments": function.get("arguments") or {},
                    }
                )
            )
    if parsed_calls:
        return parsed_calls

    content = message.get("content")
    if isinstance(content, str) and content.strip():
        return _parse_expert_tool_call_content(content)
    raise HTTPException(status_code=502, detail="DeepSeek did not return expert tool calls.")


def _parse_expert_tool_call_content(content: str) -> List[Dict[str, Any]]:
    stripped = content.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", stripped, flags=re.IGNORECASE | re.DOTALL)
    if fence:
        stripped = fence.group(1).strip()
    if not stripped.startswith("{"):
        start = stripped.find("{")
        end = stripped.rfind("}")
        if start < 0 or end <= start:
            raise ValueError("No JSON object was found.")
        stripped = stripped[start : end + 1]
    try:
        payload = json.loads(stripped)
    except json.JSONDecodeError as exc:
        raise ValueError("JSON object could not be decoded.") from exc
    if not isinstance(payload, dict):
        raise ValueError("Tool call payload must be a JSON object.")
    return _normalize_expert_tool_calls(payload)


def _complete_expert_tool_calls(
    message: str,
    context: Optional[AgentPageContext],
    tool_calls: List[Dict[str, Any]],
    settings: Any,
) -> List[Dict[str, Any]]:
    completed = list(tool_calls)
    names = _expert_tool_names(completed)
    needs_search = _expert_message_requests_search(message)
    needs_prepare = _expert_message_requests_prepare(message)
    needs_run = _expert_message_requests_map_output(message)
    has_prepared_dataset = _expert_context_has_prepared_dataset(context)

    if needs_search and _EXPERT_TOOL_SEARCH_REMOTE_SENSING_IMAGES not in names:
        completed.insert(
            0,
            {
                "name": _EXPERT_TOOL_SEARCH_REMOTE_SENSING_IMAGES,
                "arguments": {},
            },
        )
        names = _expert_tool_names(completed)

    if (
        (needs_prepare or (needs_run and not has_prepared_dataset))
        and _EXPERT_TOOL_PREPARE_REMOTE_SENSING_BASEMAP not in names
    ):
        insert_at = _expert_insert_index_after(
            completed,
            _EXPERT_TOOL_SEARCH_REMOTE_SENSING_IMAGES,
        )
        completed.insert(
            insert_at,
            {
                "name": _EXPERT_TOOL_PREPARE_REMOTE_SENSING_BASEMAP,
                "arguments": {},
            },
        )
        names = _expert_tool_names(completed)

    if needs_run and _EXPERT_TOOL_RUN_ARCPY_CODE not in names:
        completed.append(_generate_expert_run_arcpy_tool_call(message, context, settings))

    return _normalize_expert_tool_calls(
        _apply_cartographic_standards_to_expert_tool_calls(message, completed)
    )


def _apply_cartographic_standards_to_expert_tool_calls(
    message: str,
    tool_calls: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    return apply_cartographic_standards_to_tool_calls(message, tool_calls)


def _generate_expert_run_arcpy_tool_call(
    message: str,
    context: Optional[AgentPageContext],
    settings: Any,
) -> Dict[str, Any]:
    context_json = json.dumps(context.model_dump() if context else {}, ensure_ascii=False, indent=2)
    knowledge_prompt = _expert_knowledge_prompt(message, settings)
    system_prompt = (
        "You are an expert ArcGIS Pro ArcPy cartographer. Generate one complete Python script, "
        "with no Markdown fences and no explanation. The server will define APRX_PATH, "
        "OUTPUT_DIR, OUTPUT_PATH, DPI, and CONTEXT. Previous data tools may inject "
        "CONTEXT['prepared_dataset_path'] before this script runs. If prepared_dataset_path is "
        "present, add that raster to the first map, set the first layout map frame extent to the "
        "added layer extent with about 8 percent padding, apply requested title/layout changes, "
        "save the APRX, and export the first layout to OUTPUT_PATH. The script must create "
        "OUTPUT_PATH. For text typography such as title font family, font size, or font style, "
        "prefer the run_arcpy_code text_styles argument when returning tool calls.\n\n"
        "Use this project knowledge as authoritative runtime guidance:\n\n"
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
    code = _repair_generated_arcpy_code(code)
    return _create_run_arcpy_code_tool_call(
        code,
        output_format=_extract_expert_output_format(message),
    )


def _expert_tool_names(tool_calls: List[Dict[str, Any]]) -> set[str]:
    return {str(call.get("name") or "") for call in tool_calls}


def _expert_insert_index_after(tool_calls: List[Dict[str, Any]], tool_name: str) -> int:
    for index, call in enumerate(tool_calls):
        if call.get("name") == tool_name:
            return index + 1
    return len(tool_calls)


def _expert_context_has_prepared_dataset(context: Optional[AgentPageContext]) -> bool:
    return bool(context and context.prepared_dataset_path)


def _expert_message_requests_search(message: str) -> bool:
    return _expert_message_has_any(
        message,
        (
            "search",
            "find",
            "query",
            "remote sensing",
            "\u641c\u7d22",
            "\u67e5\u627e",
            "\u67e5\u8be2",
            "\u9065\u611f",
            "\u5f71\u50cf",
        ),
    )


def _expert_message_requests_prepare(message: str) -> bool:
    return _expert_message_has_any(
        message,
        (
            "prepare",
            "raster",
            "basemap",
            "rgb",
            "\u51c6\u5907",
            "\u6805\u683c",
            "\u5e95\u56fe",
        ),
    )


def _expert_message_requests_map_output(message: str) -> bool:
    return _expert_message_has_any(
        message,
        (
            "map",
            "export",
            "jpg",
            "jpeg",
            "png",
            "pdf",
            "title",
            "\u5236\u4f5c",
            "\u751f\u6210",
            "\u5236\u56fe",
            "\u5730\u56fe",
            "\u5bfc\u51fa",
            "\u6807\u9898",
        ),
    )


def _expert_message_has_any(message: str, patterns: tuple[str, ...]) -> bool:
    lowered = message.lower()
    return any(pattern in lowered for pattern in patterns)


def _extract_expert_output_format(message: str) -> str:
    lowered = message.lower()
    if "pdf" in lowered:
        return "pdf"
    if "png" in lowered:
        return "png"
    return "jpg"


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
    message = _deepseek_chat_completion(
        settings=settings,
        messages=messages,
        temperature=temperature,
    )
    content = message.get("content")
    if not isinstance(content, str) or not content.strip():
        raise HTTPException(status_code=502, detail="DeepSeek response message was empty.")
    return content.strip()


def _deepseek_chat_completion(
    *,
    settings: Any,
    messages: List[Dict[str, str]],
    temperature: float,
    tools: Optional[List[Dict[str, Any]]] = None,
    tool_choice: Optional[Any] = None,
) -> Dict[str, Any]:
    request_payload: Dict[str, Any] = {
        "model": settings.deepseek_model,
        "messages": messages,
        "temperature": temperature,
        "stream": False,
    }
    if tools is not None:
        request_payload["tools"] = tools
    if tool_choice is not None:
        request_payload["tool_choice"] = tool_choice

    request_body = json.dumps(request_payload).encode("utf-8")
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
        message = upstream_payload["choices"][0]["message"]
    except (KeyError, IndexError, TypeError) as exc:
        raise HTTPException(
            status_code=502,
            detail="DeepSeek response did not include a message.",
        ) from exc

    if not isinstance(message, dict):
        raise HTTPException(status_code=502, detail="DeepSeek response message was invalid.")
    return message


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

from __future__ import annotations

from app.agents.cartography.skills.data_acquisition import (
    build_pending_image_selection,
    build_search_payload,
)
from app.agents.cartography.skills.cartographic_standards import build_text_styles_from_request
from app.agents.cartography.skills.cartographic_standards import (
    build_layout_element_positions_from_request,
    build_layout_operations_from_request,
)
from app.agents.cartography.skills.remote_sensing_basemap import build_prepare_payload
from app.api.routes.agent import (
    AgentPageContext,
    _complete_expert_tool_calls,
    _create_run_arcpy_code_tool_call,
    _create_expert_task,
    _create_task,
    _execute_expert_tool_call,
    _ensure_prepared_dataset_loaded,
    _expert_tool_calls_from_user_message,
    _extract_layout_elements,
    _extract_layout_page,
    _is_supported_agent_request,
    _normalize_expert_tool_call,
    _parse_expert_tool_call_content,
    _repair_generated_arcpy_code,
    _select_expert_knowledge_files,
    _strip_generated_layout_operation_blocks,
    _tool_render_research_area_overview_map,
    _tool_call_with_selected_item,
)


def test_extract_north_arrow_bottom_left_layout_element() -> None:
    elements = _extract_layout_elements("做一张研究区示意图，把指北针放到左下角")

    assert elements == [
        {
            "element_name": "zbz",
            "anchor": "bottom_left",
            "offset_x": 0.3,
            "offset_y": 0.3,
        }
    ]


def test_extract_a4_landscape_page() -> None:
    assert _extract_layout_page("做一张A4横版研究区示意图") == {
        "size": "a4",
        "orientation": "landscape",
    }


def test_north_arrow_position_is_supported_agent_request() -> None:
    assert _is_supported_agent_request("把指北针放到左下角")


def test_extract_north_arrow_top_right_uses_inset_direction() -> None:
    elements = _extract_layout_elements("把指北针放右上角，边距0.5")

    assert elements == [
        {
            "element_name": "zbz",
            "anchor": "top_right",
            "offset_x": -0.5,
            "offset_y": -0.5,
        }
    ]


def test_create_task_carries_layout_elements_into_map_spec() -> None:
    context = AgentPageContext(
        collection="landsat-c2-l2",
        bbox=[100.0, 20.0, 101.0, 21.0],
        layout_name="布局",
    )

    task = _create_task("做一张研究区示意图，把指北针放到左下角", context)

    assert task.map_spec["layout"]["layout_elements"] == [
        {
            "element_name": "zbz",
            "anchor": "bottom_left",
            "offset_x": 0.3,
            "offset_y": 0.3,
        }
    ]


def test_create_task_carries_page_into_map_spec() -> None:
    context = AgentPageContext(
        collection="landsat-c2-l2",
        bbox=[100.0, 20.0, 101.0, 21.0],
        layout_name="布局",
    )

    task = _create_task("做一张A4横版研究区示意图", context)

    assert task.map_spec["layout"]["page"] == {
        "size": "a4",
        "orientation": "landscape",
    }


def test_create_expert_task_carries_prepared_dataset_path_into_context() -> None:
    context = AgentPageContext(
        collection="landsat-c2-l2",
        bbox=[100.0, 20.0, 101.0, 21.0],
        prepared_dataset_path="C:\\data-service\\cache\\prepared\\demo.tif",
    )

    task = _create_expert_task("专家制图", context, _create_run_arcpy_code_tool_call("print('ok')"))

    assert task.map_spec["context"]["prepared_dataset_path"] == (
        "C:\\data-service\\cache\\prepared\\demo.tif"
    )


def test_complete_expert_tool_calls_uses_context_layout_elements() -> None:
    context = AgentPageContext(
        collection="landsat-c2-l2",
        bbox=[100.0, 20.0, 101.0, 21.0],
        layout_elements=[
            {"element_name": "zbz", "x": 120.0, "y": 73.0, "units": "millimeter"},
            {"element_name": "比例尺", "x": 16.0, "y": 8.0, "units": "millimeter"},
        ],
    )

    tool_calls = _complete_expert_tool_calls(
        "按当前版面生成地图",
        context,
        [_create_run_arcpy_code_tool_call("print('ok')")],
        None,
    )
    run_call = tool_calls[0]

    assert run_call["arguments"]["layout_elements"] == [
        {"element_name": "zbz", "x": 120.0, "y": 73.0, "units": "millimeter"},
        {"element_name": "比例尺", "x": 16.0, "y": 8.0, "units": "millimeter"},
    ]


def test_explicit_expert_layout_request_overrides_context_layout_element() -> None:
    context = AgentPageContext(
        collection="landsat-c2-l2",
        bbox=[100.0, 20.0, 101.0, 21.0],
        layout_elements=[
            {"element_name": "zbz", "x": 120.0, "y": 73.0, "units": "millimeter"},
        ],
    )

    tool_calls = _complete_expert_tool_calls(
        "生成地图，指北针位置 x=2 y=2",
        context,
        [_create_run_arcpy_code_tool_call("print('ok')")],
        None,
    )
    run_call = tool_calls[0]

    assert run_call["arguments"]["layout_elements"] == [
        {"element_name": "zbz", "x": 2.0, "y": 2.0, "units": "inch"},
    ]


def test_create_expert_task_uses_tool_call_output_options() -> None:
    task = _create_expert_task(
        "专家制图",
        None,
        _create_run_arcpy_code_tool_call(
            "print('ok')",
            output_format="pdf",
            dpi=400,
            template_id="default",
        ),
    )

    assert task.kind == "expert_tool_call"
    assert task.steps[0].name == "run_arcpy_code"
    assert task.map_spec["output"] == {"format": "pdf", "dpi": 400}
    assert task.outputs["tool_calls"][0]["arguments"]["code"] == "print('ok')"


def test_parse_expert_tool_call_content_accepts_json_wrapper() -> None:
    tool_calls = _parse_expert_tool_call_content(
        """
        {
          "tool_calls": [
            {
              "name": "search_remote_sensing_images",
              "arguments": {
                "limit": 5
              }
            },
            {
              "name": "prepare_remote_sensing_basemap",
              "arguments": {}
            },
            {
              "name": "run_arcpy_code",
              "arguments": {
                "code": "print('ok')",
                "output_format": "jpeg",
                "dpi": 300
              }
            }
          ]
        }
        """
    )

    assert tool_calls == [
        {
            "name": "search_remote_sensing_images",
            "arguments": {
                "limit": 5,
            },
        },
        {
            "name": "prepare_remote_sensing_basemap",
            "arguments": {},
        },
        {
            "name": "run_arcpy_code",
            "arguments": {
                "code": "print('ok')",
                "output_format": "jpg",
                "dpi": 300,
                "template_id": "default",
            },
        },
    ]


def test_normalize_expert_run_arcpy_accepts_text_styles() -> None:
    tool_call = _normalize_expert_tool_call(
        {
            "name": "run_arcpy_code",
            "arguments": {
                "code": "print('ok')",
                "text_styles": [
                    {
                        "element_name": "Title",
                        "font_family": "Times New Roman",
                        "font_size": "6",
                        "font_style": "Bold",
                    }
                ],
            },
        }
    )

    assert tool_call["arguments"]["text_styles"] == [
        {
            "element_name": "Title",
            "font_family": "Times New Roman",
            "font_style": "Bold",
            "font_size": 6.0,
        }
    ]


def test_normalize_expert_run_arcpy_accepts_layout_operations() -> None:
    tool_call = _normalize_expert_tool_call(
        {
            "name": "run_arcpy_code",
            "arguments": {
                "code": "print('ok')",
                "layout_operations": [
                    {
                        "type": "ensure_scale_bar",
                        "anchor": "bottom_left",
                        "width": "4",
                        "height": "0.5",
                        "units": "centimeter",
                    },
                    {"type": "ensure_grid"},
                ],
            },
        }
    )

    assert tool_call["arguments"]["layout_operations"] == [
        {
            "type": "ensure_scale_bar",
            "anchor": "bottom_left",
            "width": 4.0,
            "height": 0.5,
            "units": "centimeter",
        },
        {"type": "ensure_grid"},
    ]


def test_cartographic_standards_skill_builds_title_text_style() -> None:
    text_styles = build_text_styles_from_request("生成地图，标题字体 Times New Roman，字号 6，加粗")

    assert text_styles == [
        {
            "element_name": "Title",
            "font_family": "Times New Roman",
            "font_size": 6.0,
            "font_style": "Bold",
            "required": True,
        }
    ]


def test_cartographic_standards_skill_builds_layout_positions() -> None:
    layout_elements = build_layout_element_positions_from_request(
        "标题位置 x=7 y=5.2，比例尺位置 x=6 y=3，指北针位置 x=2 y=2"
    )

    assert layout_elements == [
        {"element_name": "Title", "x": 7.0, "y": 5.2, "units": "inch"},
        {"element_name": "比例尺", "x": 6.0, "y": 3.0, "units": "inch"},
        {"element_name": "zbz", "x": 2.0, "y": 2.0, "units": "inch"},
    ]


def test_cartographic_standards_skill_builds_anchor_positions_with_offsets() -> None:
    layout_elements = build_layout_element_positions_from_request(
        "比例尺放到左下角，往上移动1厘米。指北针放到右上角，往左移动0.5厘米"
    )

    assert layout_elements == [
        {
            "element_name": "比例尺",
            "anchor": "bottom_left",
            "offset_y": 1.0,
            "units": "centimeter",
        },
        {
            "element_name": "zbz",
            "anchor": "top_right",
            "offset_x": -0.5,
            "units": "centimeter",
        },
    ]


def test_cartographic_standards_skill_builds_layout_operations() -> None:
    operations = build_layout_operations_from_request(
        "生成地图，添加比例尺放到左下角，添加指北针放到右上角，加格网，小图放到右下角"
    )

    assert operations == [
        {"type": "ensure_scale_bar", "name": "比例尺", "anchor": "bottom_left", "units": "inch"},
        {"type": "ensure_north_arrow", "name": "zbz", "anchor": "top_right", "units": "inch"},
        {"type": "ensure_grid"},
        {
            "type": "ensure_inset_map",
            "name": "Inset Map Frame",
            "anchor": "bottom_right",
            "units": "inch",
        },
    ]


def test_complete_expert_tool_calls_applies_cartographic_standards(monkeypatch) -> None:
    context = AgentPageContext(
        collection="landsat-c2-l2",
        bbox=[100.0, 20.0, 101.0, 21.0],
        prepared_dataset_path="C:\\data-service\\cache\\prepared\\demo.tif",
    )

    monkeypatch.setattr(
        "app.api.routes.agent._generate_expert_run_arcpy_tool_call",
        lambda message, context, settings: _create_run_arcpy_code_tool_call("print('ok')"),
    )

    tool_calls = _complete_expert_tool_calls(
        "生成该区域的遥感影像地图，标题为 waamj，输出 jpg，标题字体 Times New Roman，字号 6，加粗",
        context,
        [],
        object(),
    )

    run_call = tool_calls[-1]
    assert run_call["name"] == "run_arcpy_code"
    assert run_call["arguments"]["text_styles"] == [
        {
            "element_name": "Title",
            "font_family": "Times New Roman",
            "font_size": 6.0,
            "font_style": "Bold",
            "required": True,
        }
    ]


def test_complete_expert_tool_calls_applies_layout_positions(monkeypatch) -> None:
    context = AgentPageContext(
        collection="landsat-c2-l2",
        bbox=[100.0, 20.0, 101.0, 21.0],
        prepared_dataset_path="C:\\data-service\\cache\\prepared\\demo.tif",
    )

    monkeypatch.setattr(
        "app.api.routes.agent._generate_expert_run_arcpy_tool_call",
        lambda message, context, settings: _create_run_arcpy_code_tool_call("print('ok')"),
    )

    tool_calls = _complete_expert_tool_calls(
        "生成地图，标题位置 x=7 y=5.2，比例尺位置 x=6 y=3，指北针位置 x=2 y=2",
        context,
        [],
        object(),
    )

    run_call = tool_calls[-1]
    assert run_call["arguments"]["layout_elements"] == [
        {"element_name": "Title", "x": 7.0, "y": 5.2, "units": "inch"},
        {"element_name": "比例尺", "x": 6.0, "y": 3.0, "units": "inch"},
        {"element_name": "zbz", "x": 2.0, "y": 2.0, "units": "inch"},
    ]


def test_complete_expert_tool_calls_applies_anchor_positions(monkeypatch) -> None:
    context = AgentPageContext(
        collection="landsat-c2-l2",
        bbox=[100.0, 20.0, 101.0, 21.0],
        prepared_dataset_path="C:\\data-service\\cache\\prepared\\demo.tif",
    )

    monkeypatch.setattr(
        "app.api.routes.agent._generate_expert_run_arcpy_tool_call",
        lambda message, context, settings: _create_run_arcpy_code_tool_call("print('ok')"),
    )

    tool_calls = _complete_expert_tool_calls(
        "生成地图，标题放到上方居中，比例尺放到左下角，往上移动1厘米，指北针放到右上角",
        context,
        [],
        object(),
    )

    run_call = tool_calls[-1]
    assert run_call["arguments"]["layout_elements"] == [
        {"element_name": "Title", "anchor": "top_center", "units": "inch"},
        {
            "element_name": "比例尺",
            "anchor": "bottom_left",
            "offset_y": 1.0,
            "units": "centimeter",
        },
        {"element_name": "zbz", "anchor": "top_right", "units": "inch"},
    ]


def test_complete_expert_tool_calls_applies_layout_operations(monkeypatch) -> None:
    context = AgentPageContext(
        collection="landsat-c2-l2",
        bbox=[100.0, 20.0, 101.0, 21.0],
        prepared_dataset_path="C:\\data-service\\cache\\prepared\\demo.tif",
    )

    monkeypatch.setattr(
        "app.api.routes.agent._generate_expert_run_arcpy_tool_call",
        lambda message, context, settings: _create_run_arcpy_code_tool_call("print('ok')"),
    )

    tool_calls = _complete_expert_tool_calls(
        "生成地图，添加比例尺放到左下角，添加指北针放到右上角，加格网，小图放到右下角",
        context,
        [],
        object(),
    )

    run_call = tool_calls[-1]
    assert run_call["arguments"]["layout_operations"] == [
        {"type": "ensure_scale_bar", "name": "比例尺", "anchor": "bottom_left", "units": "inch"},
        {"type": "ensure_north_arrow", "name": "zbz", "anchor": "top_right", "units": "inch"},
        {"type": "ensure_grid"},
        {
            "type": "ensure_inset_map",
            "name": "Inset Map Frame",
            "anchor": "bottom_right",
            "units": "inch",
        },
    ]


def test_create_expert_task_can_queue_search_prepare_and_run() -> None:
    context = AgentPageContext(
        collection="landsat-c2-l2",
        bbox=[100.0, 20.0, 101.0, 21.0],
    )

    task = _create_expert_task(
        "专家制图",
        context,
        [
            {"name": "search_remote_sensing_images", "arguments": {"limit": 5}},
            {"name": "prepare_remote_sensing_basemap", "arguments": {}},
            _create_run_arcpy_code_tool_call("print('ok')"),
        ],
    )

    assert [step.name for step in task.steps] == [
        "search_remote_sensing_images",
        "select_remote_sensing_image",
        "prepare_remote_sensing_basemap",
        "run_arcpy_code",
        "check_expert_output",
    ]
    assert task.map_spec["basemap"]["limit"] == 5
    assert task.outputs["tool_calls"][0]["name"] == "search_remote_sensing_images"


def test_complete_expert_tool_calls_backfills_prepare_and_run(monkeypatch) -> None:
    context = AgentPageContext(
        collection="landsat-c2-l2",
        bbox=[100.0, 20.0, 101.0, 21.0],
    )

    monkeypatch.setattr(
        "app.api.routes.agent._generate_expert_run_arcpy_tool_call",
        lambda message, context, settings: _create_run_arcpy_code_tool_call("print('ok')"),
    )

    tool_calls = _complete_expert_tool_calls(
        "搜索当前范围的遥感影像，准备RGB栅格，然后制作一张标题为 mj 的300dpi JPG地图",
        context,
        [{"name": "search_remote_sensing_images", "arguments": {}}],
        object(),
    )

    assert [call["name"] for call in tool_calls] == [
        "search_remote_sensing_images",
        "prepare_remote_sensing_basemap",
        "run_arcpy_code",
    ]


def test_expert_remote_sensing_map_request_defers_code_generation(monkeypatch) -> None:
    context = AgentPageContext(
        collection="sentinel-2-l2a",
        bbox=[116.3, 39.85, 116.45, 39.95],
    )

    monkeypatch.setattr(
        "app.api.routes.agent._generate_expert_tool_calls",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("DeepSeek should not run")),
    )

    tool_calls = _expert_tool_calls_from_user_message(
        "生成该区域的遥感影像图，指北针放中间，比例尺放左上角，添加格网，导出为jpg",
        context,
        object(),
    )

    assert [call["name"] for call in tool_calls] == [
        "search_remote_sensing_images",
        "prepare_remote_sensing_basemap",
    ]
    assert tool_calls[0]["arguments"]["collection"] == "sentinel-2-l2a"
    assert tool_calls[0]["arguments"]["bbox"] == [116.3, 39.85, 116.45, 39.95]


def test_create_expert_task_tracks_deferred_run_arcpy_step() -> None:
    context = AgentPageContext(
        collection="sentinel-2-l2a",
        bbox=[116.3, 39.85, 116.45, 39.95],
    )

    task = _create_expert_task(
        "生成该区域的遥感影像图，指北针放中间，比例尺放左上角，添加格网，导出为jpg",
        context,
        [
            {"name": "search_remote_sensing_images", "arguments": {}},
            {"name": "prepare_remote_sensing_basemap", "arguments": {}},
        ],
    )

    assert task.outputs["deferred_run_arcpy"] is True
    assert [step.name for step in task.steps] == [
        "search_remote_sensing_images",
        "select_remote_sensing_image",
        "prepare_remote_sensing_basemap",
        "run_arcpy_code",
        "check_expert_output",
    ]


def test_data_acquisition_skill_builds_search_payload_and_pending_action() -> None:
    payload = build_search_payload(
        {
            "study_area": {
                "bbox": [100.0, 20.0, 101.0, 21.0],
                "geometry": None,
            },
            "basemap": {
                "provider": "mpc",
                "collection": "landsat-c2-l2",
                "datetime": "2025-03-01/2025-05-31",
                "limit": 500,
                "cloud_cover_lte": 20,
            },
        }
    )
    pending_action = build_pending_image_selection(
        {"item": {"item_id": "image-1"}, "summary": "Recommended image image-1."}
    )

    assert payload == {
        "provider": "mpc",
        "collection": "landsat-c2-l2",
        "bbox": [100.0, 20.0, 101.0, 21.0],
        "datetime": "2025-03-01/2025-05-31",
        "limit": 100,
        "cloud_cover_lte": 20.0,
    }
    assert pending_action == {
        "type": "select_image",
        "message": "Select one candidate image to continue the expert map task.",
        "recommended_item_id": "image-1",
    }


def test_remote_sensing_basemap_skill_builds_prepare_payload() -> None:
    payload = build_prepare_payload(
        {
            "map_kind": "expert_tool_call",
            "study_area": {
                "bbox": [100.0, 20.0, 101.0, 21.0],
                "geometry": None,
            },
            "basemap": {
                "provider": "mpc",
                "collection": "landsat-c2-l2",
                "bands": ["red", "green", "blue"],
                "target_resolution": 30,
                "target_crs": "EPSG:3857",
            },
        },
        {"item": {"item_id": "image-2"}},
    )

    assert payload["item_id"] == "image-2"
    assert payload["bbox_crs"] == "EPSG:4326"
    assert payload["output"] == {"format": "geotiff", "purpose": "carto-render"}
    assert payload["metadata"]["skill_id"] == "remote_sensing_basemap"


def test_expert_prepare_tool_updates_context_with_prepared_dataset(monkeypatch) -> None:
    context = AgentPageContext(
        collection="landsat-c2-l2",
        bbox=[100.0, 20.0, 101.0, 21.0],
    )
    task = _create_expert_task(
        "专家制图",
        context,
        [
            {"name": "search_remote_sensing_images", "arguments": {}},
            {"name": "prepare_remote_sensing_basemap", "arguments": {}},
        ],
    )

    def fake_post_json(url, payload):
        if url.endswith("/searches"):
            return {
                "items": [
                    {
                        "item_id": "image-1",
                        "datetime": "2026-01-01T00:00:00Z",
                        "cloud_cover": 1.0,
                    }
                ]
            }
        if url.endswith("/prepare-jobs"):
            return {"job": {"id": "prepare-1"}}
        raise AssertionError(url)

    def fake_poll_job(base_url, job_id, *, timeout_seconds):
        return {
            "id": job_id,
            "status": "done",
            "result": {"dataset": {"dataset_id": "dataset-1", "path": "C:\\data\\demo.tif"}},
        }

    monkeypatch.setattr("app.api.routes.agent._post_json", fake_post_json)
    monkeypatch.setattr("app.api.routes.agent._poll_job", fake_poll_job)

    search_result = _execute_expert_tool_call(
        task,
        task.outputs["tool_calls"][0],
        type("Settings", (), {"data_service_url": "http://127.0.0.1:8010"})(),
    )
    task.outputs = {**task.outputs, "search": search_result}
    prepare_result = _execute_expert_tool_call(
        task,
        task.outputs["tool_calls"][1],
        type("Settings", (), {"data_service_url": "http://127.0.0.1:8010"})(),
    )

    assert prepare_result["dataset"]["path"] == "C:\\data\\demo.tif"
    assert task.map_spec["context"]["prepared_dataset_path"] == "C:\\data\\demo.tif"


def test_prepare_tool_call_uses_user_selected_image() -> None:
    tool_call = {
        "name": "prepare_remote_sensing_basemap",
        "arguments": {"bands": ["red", "green", "blue"]},
    }

    next_call = _tool_call_with_selected_item(tool_call, "user-image-2")

    assert next_call["arguments"]["item_id"] == "user-image-2"
    assert next_call["arguments"]["bands"] == ["red", "green", "blue"]


def test_repair_generated_arcpy_code_fixes_legacy_text_element_signature() -> None:
    repaired = _repair_generated_arcpy_code(
        """
import arcpy
aprx = arcpy.mp.ArcGISProject(APRX_PATH)
layout = aprx.listLayouts()[0]
map_title = CONTEXT.get("map_title")
page_width = layout.pageWidth
page_height = layout.pageHeight
text_elem = aprx.createTextElement(
    map_title,
    "TEXT",
    "Title",
    (page_width / 2.0, page_height - 28.0)
)
"""
    )

    assert 'aprx.createTextElement(layout, arcpy.Point(page_width / 2.0, page_height - 0.35), \'POINT\', map_title' in repaired
    assert "name='Title'" in repaired


def test_repair_generated_arcpy_code_fixes_layout_text_element_signature() -> None:
    repaired = _repair_generated_arcpy_code(
        """
import arcpy
aprx = arcpy.mp.ArcGISProject(APRX_PATH)
layout = aprx.listLayouts()[0]
page_width = layout.pageWidth
page_height = layout.pageHeight
title_text = CONTEXT.get('map_title', 'Landsat Map')
title = layout.createTextElement(title_text, 'Title')
"""
    )

    assert "aprx.createTextElement(layout, arcpy.Point(page_width / 2.0, page_height - 0.35), 'POINT', title_text" in repaired
    assert "name='Title'" in repaired


def test_repair_generated_arcpy_code_fixes_layout_point_text_signature() -> None:
    repaired = _repair_generated_arcpy_code(
        """
import arcpy
aprx = arcpy.mp.ArcGISProject(APRX_PATH)
layout = aprx.listLayouts()[0]
def ensure_title(layout, text):
    title = layout.createTextElement(
        arcpy.Point(layout.pageWidth / 2, layout.pageHeight - 0.5),
        text,
        'POINT'
    )
    return title
"""
    )

    assert (
        "aprx.createTextElement(layout, arcpy.Point(layout.pageWidth / 2, "
        "layout.pageHeight - 0.5), 'POINT', text"
    ) in repaired
    assert "name='Title'" in repaired


def test_expert_knowledge_always_includes_layout_text_runtime_rules() -> None:
    files = _select_expert_knowledge_files("生成该区域的遥感影像图，导出为jpg")

    assert "arcpy_layout_text.md" in files
    assert "arcpy_layout_elements.md" in files


def test_repair_generated_arcpy_code_fixes_aprx_text_element_position_dict() -> None:
    repaired = _repair_generated_arcpy_code(
        """
import arcpy
aprx = arcpy.mp.ArcGISProject(APRX_PATH)
layout = aprx.listLayouts()[0]
map_title = CONTEXT.get('map_title', 'Landsat Map')
page_width = layout.pageWidth
page_height = layout.pageHeight
title_elem = aprx.createTextElement(map_title, {'x': page_width / 2, 'y': page_height - 0.8, 'anchor': 'TOP_CENTER'})
"""
    )

    assert "aprx.createTextElement(layout, arcpy.Point(page_width / 2, page_height - 0.8), 'POINT', map_title" in repaired
    assert "name='Title'" in repaired


def test_strip_generated_layout_operation_blocks_removes_unstable_surround_code() -> None:
    stripped = _strip_generated_layout_operation_blocks(
        """
if main_extent:
    map_frame.camera.setExtent(main_extent)
scale_bar_matches = layout.listElements('MAPSURROUND_ELEMENT', 'Scale Bar')
if scale_bar_matches:
    scale_bar = scale_bar_matches[0]
else:
    scale_bar = layout.createMapSurround(map_frame, 'SCALE_BAR', 'Scale Bar')
scale_bar.setAnchor('BOTTOM_LEFT_CORNER')
na_matches = layout.listElements('MAPSURROUND_ELEMENT', 'zbz')
if na_matches:
    north_arrow = na_matches[0]
else:
    north_arrow = layout.createMapSurround(map_frame, 'NORTH_ARROW', 'North Arrow')
inset_matches = layout.listElements('MAPFRAME_ELEMENT', 'Inset Map')
if inset_matches:
    inset_mf = inset_matches[0]
else:
    inset_mf = layout.cloneElement(map_frame)
grids = map_frame.mapGrids
if not grids:
    map_frame.createMapGrid('GRATICULE', 'Graticule')
title_text = CONTEXT.get('map_title', 'Landsat Map')
title = layout.createTextElement(title_text, 'Title')
aprx.save()
""",
        [
            {"type": "ensure_scale_bar"},
            {"type": "ensure_north_arrow"},
            {"type": "ensure_grid"},
            {"type": "ensure_inset_map"},
        ],
    )

    assert "createMapSurround" not in stripped
    assert "cloneElement" not in stripped
    assert "createMapGrid" not in stripped
    assert "title_text = CONTEXT.get" in stripped
    assert "aprx.save()" in stripped


def test_strip_generated_layout_operation_blocks_removes_helper_functions() -> None:
    stripped = _strip_generated_layout_operation_blocks(
        """
import arcpy
aprx = arcpy.mp.ArcGISProject(APRX_PATH)
layout = aprx.listLayouts()[0]
map_frame = layout.listElements('MAPFRAME_ELEMENT')[0]

def ensure_grid(mf):
    for method_name in ['addMapGrid', 'addGrid']:
        if hasattr(mf, method_name):
            return getattr(mf, method_name)('Graticule')
    raise RuntimeError('Failed to add map grid')

def ensure_scale_bar(lyt, mf):
    return lyt.addMapSurround(mf, 'Scale Bar', 'Scale Bar')

def keep_extent():
    map_frame.camera.scale = 10000

grid = ensure_grid(map_frame)
scale_bar = ensure_scale_bar(layout, map_frame)
keep_extent()
aprx.save()
layout.exportToJPEG(OUTPUT_PATH, resolution=DPI)
""",
        [
            {"type": "ensure_scale_bar"},
            {"type": "ensure_grid"},
        ],
    )

    assert "def ensure_grid" not in stripped
    assert "def ensure_scale_bar" not in stripped
    assert "ensure_grid(map_frame)" not in stripped
    assert "ensure_scale_bar(layout, map_frame)" not in stripped
    assert "def keep_extent" in stripped
    assert "keep_extent()" in stripped
    assert "aprx.save()" in stripped
    assert "layout.exportToJPEG" in stripped


def test_ensure_prepared_dataset_loaded_injects_missing_raster_layer() -> None:
    code = """
import arcpy
aprx = arcpy.mp.ArcGISProject(APRX_PATH)
layout = aprx.listLayouts()[0]
title = aprx.createTextElement(layout, arcpy.Point(1, 1), "POINT", "waamj")
aprx.save()
layout.exportToJPEG(OUTPUT_PATH, resolution=DPI)
"""

    repaired = _ensure_prepared_dataset_loaded(
        code,
        {"context": {"prepared_dataset_path": "C:\\data\\prepared.tif"}},
    )

    assert "map_obj = aprx.listMaps()[0]" in repaired
    assert "added_layer = map_obj.addDataFromPath(prepared_dataset_path)" in repaired
    assert repaired.index("addDataFromPath") < repaired.index("createTextElement")


def test_render_payload_includes_layout_elements(monkeypatch) -> None:
    captured = {}

    def fake_post_json(url, payload):
        captured["url"] = url
        captured["payload"] = payload
        return {"job": {"id": "job-1"}}

    def fake_poll_job(base_url, job_id, *, timeout_seconds):
        return {
            "id": job_id,
            "status": "done",
            "result": {"files": {"preview": "C:\\outputs\\preview.png"}},
        }

    monkeypatch.setattr("app.api.routes.agent._post_json", fake_post_json)
    monkeypatch.setattr("app.api.routes.agent._poll_job", fake_poll_job)

    _tool_render_research_area_overview_map(
        {
            "layout": {
                "title": "Demo Map",
                "template_id": "default",
                "layout_name": "布局",
                "fit_padding": 0.08,
                "page": {"size": "a4", "orientation": "landscape"},
                "layout_elements": [
                    {
                        "element_name": "zbz",
                        "anchor": "bottom_left",
                        "offset_x": 0.3,
                        "offset_y": 0.3,
                    }
                ],
                "layout_operations": [
                    {
                        "type": "ensure_scale_bar",
                        "anchor": "bottom_left",
                    }
                ],
            },
            "output": {"format": "png", "dpi": 150},
        },
        {"dataset": {"path": "C:\\data\\demo.tif"}},
        {"path": "C:\\data\\study-area.geojson"},
        "http://127.0.0.1:8000",
    )

    assert captured["url"] == "http://127.0.0.1:8000/api/v1/render/preview"
    assert captured["payload"]["project"]["layout_elements"] == [
        {
            "element_name": "zbz",
            "anchor": "bottom_left",
            "offset_x": 0.3,
            "offset_y": 0.3,
        }
    ]
    assert captured["payload"]["project"]["layout_operations"] == [
        {
            "type": "ensure_scale_bar",
            "anchor": "bottom_left",
        }
    ]
    assert captured["payload"]["project"]["page"] == {
        "size": "a4",
        "orientation": "landscape",
    }

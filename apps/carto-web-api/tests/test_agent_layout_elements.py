from __future__ import annotations

from app.api.routes.agent import (
    AgentPageContext,
    _complete_expert_tool_calls,
    _create_run_arcpy_code_tool_call,
    _create_expert_task,
    _create_task,
    _execute_expert_tool_call,
    _extract_layout_elements,
    _extract_layout_page,
    _is_supported_agent_request,
    _parse_expert_tool_call_content,
    _tool_render_research_area_overview_map,
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
    assert captured["payload"]["project"]["page"] == {
        "size": "a4",
        "orientation": "landscape",
    }

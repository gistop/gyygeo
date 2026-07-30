from __future__ import annotations

from app.api.routes.agent import (
    AgentPageContext,
    _create_task,
    _extract_layout_elements,
    _extract_layout_page,
    _is_supported_agent_request,
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

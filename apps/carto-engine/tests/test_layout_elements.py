from __future__ import annotations

from pathlib import Path
from typing import List, Optional

import pytest

from app.arcpy_engine.code_runner import _typography_postprocess_source
from app.arcpy_engine.typography import apply_text_typography_operations
from app.arcpy_engine.worker import _apply_layout_element_positions, _apply_layout_page
from app.schemas.project import LayoutElementPosition, LayoutPage, RenderPreviewRequest, TextTypography


class FakeElement:
    def __init__(
        self,
        name: str,
        width: float,
        height: float,
        element_type: str,
        children: Optional[List["FakeElement"]] = None,
    ) -> None:
        self.name = name
        self.element_type = element_type
        self.elementWidth = width
        self.elementHeight = height
        self.elementPositionX = 0.0
        self.elementPositionY = 0.0
        self.anchor = None
        self.children = children or []
        self.textSize = None
        self.fontFamilyName = None
        self.fontStyleName = None

    def setAnchor(self, anchor: str) -> None:
        self.anchor = anchor

    def listElements(
        self,
        element_type: Optional[str] = None,
        wildcard: Optional[str] = None,
    ) -> List["FakeElement"]:
        return _filter_fake_elements(self.children, element_type, wildcard)


class FakeLayout:
    pageWidth = 10.0
    pageHeight = 8.0
    pageUnits = "CENTIMETER"
    valid_element_types = {
        "GRAPHIC_ELEMENT",
        "GROUP_ELEMENT",
        "LEGEND_ELEMENT",
        "MAPFRAME_ELEMENT",
        "MAPSURROUND_ELEMENT",
        "PICTURE_ELEMENT",
        "TABLEFRAME_ELEMENT",
        "TEXT_ELEMENT",
    }

    def __init__(self, elements: List[FakeElement]) -> None:
        self.elements = elements

    def listElements(
        self,
        element_type: Optional[str] = None,
        wildcard: Optional[str] = None,
    ) -> List[FakeElement]:
        return _filter_fake_elements(self.elements, element_type, wildcard)

    def changePageSize(
        self,
        page_width: float,
        page_height: float,
        resize_elements: bool = True,
    ) -> None:
        self.pageWidth = page_width
        self.pageHeight = page_height
        self.resize_elements = resize_elements


def _filter_fake_elements(
    elements: List[FakeElement],
    element_type: Optional[str],
    wildcard: Optional[str],
) -> List[FakeElement]:
        if element_type == "*":
            raise ValueError("Invalid value for element_type: '*'")
        filtered = elements
        if element_type is not None:
            if element_type not in FakeLayout.valid_element_types:
                raise ValueError(f"Invalid value for element_type: {element_type}")
            filtered = [element for element in filtered if element.element_type == element_type]
        if wildcard is None:
            return filtered
        return [element for element in filtered if element.name == wildcard]


def test_layout_element_anchor_position_uses_page_bounds() -> None:
    north_arrow = FakeElement("North Arrow", width=1.0, height=1.5, element_type="MAPSURROUND_ELEMENT")
    layout = FakeLayout([north_arrow])

    messages = _apply_layout_element_positions(
        layout,
        [
            LayoutElementPosition(
                element_name="North Arrow",
                anchor="bottom_left",
                offset_x=0.25,
                offset_y=0.5,
            )
        ],
    )

    assert north_arrow.anchor == "BOTTOM_LEFT_CORNER"
    assert north_arrow.elementPositionX == 0.25
    assert north_arrow.elementPositionY == 0.5
    assert messages == ["Moved layout element North Arrow to 0.250, 0.500"]


def test_layout_page_named_size_converts_to_layout_units() -> None:
    layout = FakeLayout([])

    messages = _apply_layout_page(layout, LayoutPage(size="a4", orientation="landscape"))

    assert layout.pageWidth == pytest.approx(29.7)
    assert layout.pageHeight == pytest.approx(21.0)
    assert layout.resize_elements is False
    assert messages == ["Changed layout page size to 29.700 x 21.000"]


def test_layout_page_orientation_only_uses_current_page_size() -> None:
    layout = FakeLayout([])

    _apply_layout_page(layout, LayoutPage(orientation="portrait"))

    assert layout.pageWidth == pytest.approx(8.0)
    assert layout.pageHeight == pytest.approx(10.0)


def test_layout_page_custom_size_converts_units() -> None:
    layout = FakeLayout([])

    _apply_layout_page(layout, LayoutPage(width=11.0, height=8.5, units="inch"))

    assert layout.pageWidth == pytest.approx(27.94)
    assert layout.pageHeight == pytest.approx(21.59)


def test_layout_element_top_right_anchor_accounts_for_element_size() -> None:
    legend = FakeElement("Legend", width=2.0, height=3.0, element_type="LEGEND_ELEMENT")
    layout = FakeLayout([legend])

    _apply_layout_element_positions(
        layout,
        [LayoutElementPosition(element_name="Legend", anchor="top_right", offset_x=-0.2)],
    )

    assert legend.elementPositionX == 7.8
    assert legend.elementPositionY == 5.0


def test_layout_element_absolute_position() -> None:
    scale_bar = FakeElement("Scale Bar", width=2.0, height=0.3, element_type="MAPSURROUND_ELEMENT")
    layout = FakeLayout([scale_bar])

    _apply_layout_element_positions(
        layout,
        [LayoutElementPosition(element_name="Scale Bar", x=2.0, y=1.0, offset_y=0.1)],
    )

    assert scale_bar.elementPositionX == 2.0
    assert scale_bar.elementPositionY == 1.1


def test_layout_element_finds_group_child() -> None:
    north_arrow = FakeElement("zbj", width=1.0, height=1.0, element_type="MAPSURROUND_ELEMENT")
    group = FakeElement("Surrounds", width=3.0, height=3.0, element_type="GROUP_ELEMENT", children=[north_arrow])
    layout = FakeLayout([group])

    _apply_layout_element_positions(
        layout,
        [LayoutElementPosition(element_name="zbj", anchor="bottom_left")],
    )

    assert north_arrow.elementPositionX == 0.0
    assert north_arrow.elementPositionY == 0.0


def test_layout_element_name_matching_ignores_case_and_spaces() -> None:
    north_arrow = FakeElement(" ZBJ ", width=1.0, height=1.0, element_type="MAPSURROUND_ELEMENT")
    layout = FakeLayout([north_arrow])

    _apply_layout_element_positions(
        layout,
        [LayoutElementPosition(element_name="zbj", anchor="bottom_left")],
    )

    assert north_arrow.elementPositionX == 0.0
    assert north_arrow.elementPositionY == 0.0


def test_missing_layout_element_lists_available_names() -> None:
    legend = FakeElement("Legend", width=2.0, height=3.0, element_type="LEGEND_ELEMENT")
    layout = FakeLayout([legend])

    with pytest.raises(RuntimeError, match="LEGEND_ELEMENT:Legend"):
        _apply_layout_element_positions(
            layout,
            [LayoutElementPosition(element_name="zbj", anchor="bottom_left")],
        )


def test_layout_element_position_rejects_mixed_anchor_and_xy() -> None:
    with pytest.raises(ValueError, match="Use either anchor or x/y"):
        LayoutElementPosition(element_name="North Arrow", anchor="bottom_left", x=1.0, y=1.0)


def test_layout_page_rejects_mixed_named_and_custom_size() -> None:
    with pytest.raises(ValueError, match="Use either page size"):
        LayoutPage(size="a4", width=10.0, height=8.0)


def test_render_request_accepts_layout_elements() -> None:
    request = RenderPreviewRequest(
        project={
            "project_name": "demo-map",
            "layout_elements": [
                {
                    "element_name": "North Arrow",
                    "anchor": "bottom_left",
                    "offset_x": 0.3,
                    "offset_y": 0.3,
                }
            ],
        },
        dry_run=True,
    )

    assert request.project.layout_elements[0].anchor == "bottom_left"


def test_render_request_accepts_page_options() -> None:
    request = RenderPreviewRequest(
        project={
            "project_name": "demo-map",
            "page": {
                "size": "A4",
                "orientation": "LANDSCAPE",
            },
        },
        dry_run=True,
    )

    assert request.project.page is not None
    assert request.project.page.size == "a4"
    assert request.project.page.orientation == "landscape"


def test_apply_text_typography_operations_updates_text_element() -> None:
    title = FakeElement("Title", width=4.0, height=0.5, element_type="TEXT_ELEMENT")
    layout = FakeLayout([title])

    messages = apply_text_typography_operations(
        layout,
        [
            TextTypography(
                element_name="Title",
                font_family="Times New Roman",
                font_size=6,
                font_style="Bold",
            )
        ],
    )

    assert title.textSize == 6.0
    assert title.fontFamilyName == "Times New Roman"
    assert title.fontStyleName == "Bold"
    assert messages == [
        "Applied typography to text element Title: font_family=Times New Roman, font_size=6, font_style=Bold"
    ]


def test_render_request_accepts_text_styles() -> None:
    request = RenderPreviewRequest(
        project={
            "project_name": "demo-map",
            "text_styles": [
                {
                    "element_name": "Title",
                    "font_family": "Times New Roman",
                    "font_size": 6,
                    "font_style": "Bold",
                }
            ],
        },
        dry_run=True,
    )

    assert request.project.text_styles[0].element_name == "Title"
    assert request.project.text_styles[0].font_size == 6


def test_typography_postprocess_source_imports_engine_typography() -> None:
    source = _typography_postprocess_source(
        base_dir=Path("C:/app"),
        aprx_path=Path("C:/tmp/work.aprx"),
        output_path=Path("C:/tmp/output.jpg"),
        output_format="jpg",
        dpi=300,
        text_styles=[
            {
                "element_name": "Title",
                "font_family": "Times New Roman",
                "font_size": 6,
            }
        ],
    )

    assert "from app.arcpy_engine.typography import apply_text_typography_operations" in source
    assert "layout.exportToJPEG(OUTPUT_PATH, resolution=DPI)" in source

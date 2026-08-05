from __future__ import annotations

from pathlib import Path
from typing import List, Optional

import pytest

from app.arcpy_engine.code_runner import _typography_postprocess_source
from app.arcpy_engine.typography import apply_text_typography_operations
from app.arcpy_engine.worker import (
    _apply_layout_element_positions,
    _apply_layout_operations,
    _apply_layout_page,
)
from app.schemas.arcpy_code import ArcPyCodeRequest
from app.schemas.project import (
    LayoutElementPosition,
    LayoutOperation,
    LayoutPage,
    RenderPreviewRequest,
    TextTypography,
)


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


class FakeGrid:
    def __init__(self, name: str) -> None:
        self.name = name


class FakeCamera:
    def __init__(self) -> None:
        self.extent = "extent"

    def getExtent(self) -> str:
        return self.extent

    def setExtent(self, extent: str) -> None:
        self.extent = extent


class FakeMapFrame(FakeElement):
    def __init__(self, name: str, width: float = 8.0, height: float = 6.0) -> None:
        super().__init__(name, width=width, height=height, element_type="MAPFRAME_ELEMENT")
        self.grids: List[FakeGrid] = []
        self.camera = FakeCamera()

    def addGrid(self, style: "FakeStyle") -> FakeGrid:
        grid = FakeGrid(style.name)
        self.grids.append(grid)
        return grid


class FakeStyle:
    def __init__(self, name: str) -> None:
        self.name = name


class FakeMap:
    name = "Map"


class FakeAprx:
    def __init__(self) -> None:
        self.map = FakeMap()

    def listStyleItems(self, gallery: str, style_class: str, style_name: str) -> List[FakeStyle]:
        return [FakeStyle(style_name)]

    def listMaps(self, name: Optional[str] = None) -> List[FakeMap]:
        if name and name != self.map.name:
            return []
        return [self.map]


class FakeArcpy:
    @staticmethod
    def Point(x: float, y: float) -> tuple[str, float, float]:
        return ("point", x, y)

    @staticmethod
    def Array(points: List[tuple[str, float, float]]) -> List[tuple[str, float, float]]:
        return points

    @staticmethod
    def Polygon(points: List[tuple[str, float, float]]) -> tuple[str, List[tuple[str, float, float]]]:
        return ("polygon", points)


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

    def createMapSurroundElement(
        self,
        geometry: object,
        surround_type: str,
        map_frame: FakeMapFrame,
        style: Optional[FakeStyle],
        name: str,
    ) -> FakeElement:
        element = FakeElement(name, width=0.0, height=0.0, element_type="MAPSURROUND_ELEMENT")
        element.geometry = geometry
        element.surround_type = surround_type
        element.map_frame = map_frame
        element.style = style
        self.elements.append(element)
        return element

    def createMapFrame(self, geometry: object, map_obj: FakeMap, name: str) -> FakeMapFrame:
        frame = FakeMapFrame(name)
        frame.geometry = geometry
        frame.map = map_obj
        self.elements.append(frame)
        return frame


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
    if wildcard == "*":
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


def test_layout_element_absolute_position_converts_units() -> None:
    scale_bar = FakeElement("比例尺", width=2.0, height=0.3, element_type="MAPSURROUND_ELEMENT")
    layout = FakeLayout([scale_bar])

    _apply_layout_element_positions(
        layout,
        [LayoutElementPosition(element_name="比例尺", x=1.0, y=2.0, units="inch")],
    )

    assert scale_bar.elementPositionX == pytest.approx(2.54)
    assert scale_bar.elementPositionY == pytest.approx(5.08)


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


def test_layout_operations_create_scale_bar_grid_and_inset_map() -> None:
    map_frame = FakeMapFrame("Main Map Frame", width=9.0, height=7.0)
    layout = FakeLayout([map_frame])
    aprx = FakeAprx()

    messages = _apply_layout_operations(
        FakeArcpy,
        aprx,
        layout,
        aprx.map,
        [
            LayoutOperation(type="ensure_scale_bar", anchor="bottom_left", width=4.0, height=0.5),
            LayoutOperation(type="ensure_grid"),
            LayoutOperation(type="ensure_inset_map", anchor="bottom_right", width=3.0, height=2.0),
        ],
    )

    scale_bar = layout.listElements("MAPSURROUND_ELEMENT", "比例尺")[0]
    inset_frame = layout.listElements("MAPFRAME_ELEMENT", "Inset Map Frame")[0]
    assert scale_bar.elementWidth == 4.0
    assert scale_bar.elementHeight == 0.5
    assert map_frame.grids[0].name == "黑色垂直标注格网"
    assert inset_frame.elementPositionX == 7.0
    assert inset_frame.elementPositionY == 0.0
    assert messages == [
        "Ensured SCALE_BAR 比例尺 at 0.000, 0.000",
        "Ensured grid 黑色垂直标注格网",
        "Ensured inset map frame Inset Map Frame at 7.000, 0.000",
    ]


def test_layout_operations_reuse_existing_north_arrow() -> None:
    map_frame = FakeMapFrame("Main Map Frame")
    north_arrow = FakeElement("zbz", width=1.0, height=1.0, element_type="MAPSURROUND_ELEMENT")
    layout = FakeLayout([map_frame, north_arrow])

    _apply_layout_operations(
        FakeArcpy,
        FakeAprx(),
        layout,
        FakeMap(),
        [LayoutOperation(type="ensure_north_arrow", anchor="top_right", offset_x=-0.5, offset_y=-0.25)],
    )

    assert len(layout.listElements("MAPSURROUND_ELEMENT", "zbz")) == 1
    assert north_arrow.elementPositionX == 8.5
    assert north_arrow.elementPositionY == 6.75


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


def test_render_request_accepts_layout_operations() -> None:
    request = RenderPreviewRequest(
        project={
            "project_name": "demo-map",
            "layout_operations": [
                {
                    "type": "ensure_scale_bar",
                    "anchor": "bottom_left",
                    "width": 4.0,
                    "height": 0.5,
                    "units": "centimeter",
                },
                {"type": "ensure_grid"},
            ],
        },
        dry_run=True,
    )

    assert request.project.layout_operations[0].type == "ensure_scale_bar"
    assert request.project.layout_operations[1].type == "ensure_grid"


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


def test_arcpy_code_request_accepts_layout_elements() -> None:
    request = ArcPyCodeRequest(
        code="print('ok')",
        layout_elements=[
            {
                "element_name": "Title",
                "x": 7.0,
                "y": 5.2,
                "units": "inch",
            }
        ],
    )

    assert request.layout_elements[0].element_name == "Title"
    assert request.layout_elements[0].x == 7.0
    assert request.layout_elements[0].units == "inch"


def test_arcpy_code_request_accepts_layout_operations() -> None:
    request = ArcPyCodeRequest(
        code="print('ok')",
        layout_operations=[
            {
                "type": "ensure_inset_map",
                "anchor": "bottom_right",
                "width": 3.0,
                "height": 2.0,
                "units": "centimeter",
            }
        ],
    )

    assert request.layout_operations[0].type == "ensure_inset_map"
    assert request.layout_operations[0].anchor == "bottom_right"


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
        layout_elements=[
            {
                "element_name": "Title",
                "x": 7.0,
                "y": 5.2,
                "units": "inch",
            }
        ],
        layout_operations=[
            {
                "type": "ensure_grid",
            }
        ],
    )

    assert "from app.arcpy_engine.typography import apply_text_typography_operations" in source
    assert "from app.arcpy_engine.worker import _apply_layout_element_positions, _apply_layout_operations" in source
    assert "layout_elements = [LayoutElementPosition(**item) for item in LAYOUT_ELEMENTS]" in source
    assert "layout_operations = [LayoutOperation(**item) for item in LAYOUT_OPERATIONS]" in source
    assert "layout.exportToJPEG(OUTPUT_PATH, resolution=DPI)" in source

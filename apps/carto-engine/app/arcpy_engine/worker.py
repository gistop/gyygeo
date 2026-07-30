from __future__ import annotations

import argparse
import json
import math
import shutil
from pathlib import Path
from typing import Any, Dict, Iterable, Optional

from app.core.config import get_settings
from app.schemas.project import LayoutElementPosition, LayoutPage, LayoutText, RenderPreviewRequest

_LAYOUT_ELEMENT_TYPES = (
    "GRAPHIC_ELEMENT",
    "GROUP_ELEMENT",
    "LEGEND_ELEMENT",
    "MAPFRAME_ELEMENT",
    "MAPSURROUND_ELEMENT",
    "PICTURE_ELEMENT",
    "TABLEFRAME_ELEMENT",
    "TEXT_ELEMENT",
)

_STANDARD_PAGE_SIZES_MM = {
    "a0": (841.0, 1189.0),
    "a1": (594.0, 841.0),
    "a2": (420.0, 594.0),
    "a3": (297.0, 420.0),
    "a4": (210.0, 297.0),
    "letter": (215.9, 279.4),
    "legal": (215.9, 355.6),
}

_PAGE_UNIT_TO_MM = {
    "MILLIMETER": 1.0,
    "MILLIMETERS": 1.0,
    "CENTIMETER": 10.0,
    "CENTIMETERS": 10.0,
    "INCH": 25.4,
    "INCHES": 25.4,
    "POINT": 25.4 / 72.0,
    "POINTS": 25.4 / 72.0,
}


def main() -> int:
    args = _parse_args()
    payload = json.loads(args.config.read_text(encoding="utf-8"))
    request = RenderPreviewRequest(**payload)
    result = render_with_arcpy(
        job_id=args.job_id,
        request=request,
        output_dir=args.output_dir,
    )
    args.result.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


def render_with_arcpy(
    *,
    job_id: str,
    request: RenderPreviewRequest,
    output_dir: Path,
) -> Dict[str, Any]:
    import arcpy  # type: ignore

    settings = get_settings()
    template_path = settings.template_dir / "aprx" / f"{request.project.template_id}.aprx"
    if not template_path.exists():
        raise FileNotFoundError(
            f"Template not found: {template_path}. Put an .aprx file in templates/aprx."
        )

    work_aprx = output_dir / "work.aprx"
    shutil.copy2(template_path, work_aprx)

    messages = []
    aprx = arcpy.mp.ArcGISProject(str(work_aprx))
    try:
        map_obj = _first_or_named_map(aprx)
        layout = _first_or_named_layout(aprx, request.project.export.layout_name)

        messages.extend(_remove_layers_by_name(map_obj, request.project.remove_layers))

        for layer_config in request.project.layers:
            if layer_config.data_source:
                added = map_obj.addDataFromPath(layer_config.data_source)
                try:
                    added.name = layer_config.name
                except Exception:
                    pass
                if hasattr(added, "visible"):
                    added.visible = layer_config.visible
                if layer_config.definition_query and hasattr(added, "definitionQuery"):
                    added.definitionQuery = layer_config.definition_query
                if hasattr(added, "transparency"):
                    added.transparency = int(round((1.0 - layer_config.opacity) * 100))
                messages.append(f"Added layer {layer_config.name}: {layer_config.data_source}")

        messages.extend(_apply_layout_page(layout, request.project.page))
        _apply_title(layout, request.project.title)
        _apply_layout_text(layout, request.project.layout_text)
        messages.extend(_apply_layout_element_positions(layout, request.project.layout_elements))
        _apply_extent(arcpy, layout, map_obj, request)

        aprx.save()
        export_path = _export_layout(layout, request, output_dir)
    finally:
        del aprx

    (output_dir / "worker.log").write_text("\n".join(messages) + "\n", encoding="utf-8")
    return {
        "job_id": job_id,
        "mode": "arcpy",
        "files": {
            "preview": str(export_path),
            "work_aprx": str(work_aprx),
            "config": str(output_dir / "config.json"),
            "worker_log": str(output_dir / "worker.log"),
        },
    }


def _first_or_named_map(aprx: Any, name: Optional[str] = None) -> Any:
    maps = aprx.listMaps(name) if name else aprx.listMaps()
    if not maps:
        raise RuntimeError("The ArcGIS project template does not contain a map.")
    return maps[0]


def _first_or_named_layout(aprx: Any, name: Optional[str] = None) -> Any:
    layouts = aprx.listLayouts(name) if name else aprx.listLayouts()
    if not layouts:
        raise RuntimeError("The ArcGIS project template does not contain a layout.")
    return layouts[0]


def _remove_layers_by_name(map_obj: Any, layer_names: Iterable[str]) -> list[str]:
    target_names = {name for name in layer_names if name}
    if not target_names:
        return []

    messages = []
    removed_names = set()
    for layer in list(map_obj.listLayers()):
        layer_name = getattr(layer, "name", "")
        if layer_name in target_names:
            map_obj.removeLayer(layer)
            removed_names.add(layer_name)
            messages.append(f"Removed layer {layer_name}")

    for missing_name in sorted(target_names - removed_names):
        messages.append(f"Layer not found for removal: {missing_name}")
    return messages


def _apply_title(layout: Any, title: Optional[str]) -> None:
    if not title:
        return
    for element in layout.listElements("TEXT_ELEMENT"):
        if element.name.lower() in {"title", "map title", "title_text"}:
            element.text = title
            return


def _apply_layout_text(layout: Any, layout_text: list[LayoutText]) -> None:
    elements = {element.name: element for element in layout.listElements("TEXT_ELEMENT")}
    for item in layout_text:
        element = elements.get(item.element_name)
        if element is not None:
            element.text = item.text


def _apply_layout_page(layout: Any, page: Optional[LayoutPage]) -> list[str]:
    if page is None:
        return []

    width, height = _layout_page_dimensions(layout, page)
    if hasattr(layout, "changePageSize"):
        layout.changePageSize(width, height, page.resize_elements)
    else:
        _set_layout_page_size(layout, width, height)

    resize_text = " with resized elements" if page.resize_elements else ""
    return [f"Changed layout page size to {width:.3f} x {height:.3f}{resize_text}"]


def _layout_page_dimensions(layout: Any, page: LayoutPage) -> tuple[float, float]:
    layout_units = _layout_page_units(layout)
    if page.size is not None:
        width, height = _convert_page_size(
            _STANDARD_PAGE_SIZES_MM[page.size],
            from_units="millimeter",
            to_units=layout_units,
        )
    elif page.width is not None and page.height is not None:
        width, height = _convert_page_size(
            (page.width, page.height),
            from_units=page.units or layout_units,
            to_units=layout_units,
        )
    else:
        width = _layout_number(layout, "pageWidth")
        height = _layout_number(layout, "pageHeight")

    if page.orientation == "landscape" and width < height:
        width, height = height, width
    elif page.orientation == "portrait" and width > height:
        width, height = height, width

    if width <= 0 or height <= 0 or not math.isfinite(width) or not math.isfinite(height):
        raise ValueError("Layout page dimensions must be positive finite numbers.")
    return width, height


def _layout_page_units(layout: Any) -> str:
    units = getattr(layout, "pageUnits", None)
    if units is None:
        raise RuntimeError("Layout is missing pageUnits.")
    return _normalized_page_units(str(units))


def _normalized_page_units(units: str) -> str:
    normalized = units.strip().upper().replace(" ", "_")
    if normalized in {"MM", "MILLIMETRE", "MILLIMETRES"}:
        normalized = "MILLIMETER"
    elif normalized in {"CM", "CENTIMETRE", "CENTIMETRES"}:
        normalized = "CENTIMETER"
    elif normalized == "IN":
        normalized = "INCH"
    if normalized not in _PAGE_UNIT_TO_MM:
        raise RuntimeError(f"Unsupported layout page units: {units}")
    return normalized


def _convert_page_size(
    size: tuple[float, float],
    *,
    from_units: str,
    to_units: str,
) -> tuple[float, float]:
    from_mm = _PAGE_UNIT_TO_MM[_normalized_page_units(from_units)]
    to_mm = _PAGE_UNIT_TO_MM[_normalized_page_units(to_units)]
    return size[0] * from_mm / to_mm, size[1] * from_mm / to_mm


def _set_layout_page_size(layout: Any, width: float, height: float) -> None:
    try:
        layout.pageWidth = width
        layout.pageHeight = height
    except Exception as exc:
        raise RuntimeError("Layout page size cannot be changed with this ArcPy runtime.") from exc


def _apply_layout_element_positions(
    layout: Any,
    positions: list[LayoutElementPosition],
) -> list[str]:
    messages = []
    if not positions:
        return messages

    for item in positions:
        element = _find_layout_element(layout, item.element_name)
        x, y = _layout_element_xy(layout, element, item)
        _set_layout_element_bottom_left_anchor(element)
        element.elementPositionX = x
        element.elementPositionY = y
        messages.append(f"Moved layout element {item.element_name} to {x:.3f}, {y:.3f}")

    return messages


def _find_layout_element(layout: Any, element_name: str) -> Any:
    candidates = _layout_elements(layout)
    for _, element in candidates:
        if getattr(element, "name", "") == element_name:
            return element
    for _, element in candidates:
        if _normalized_layout_name(getattr(element, "name", "")) == _normalized_layout_name(
            element_name
        ):
            return element

    available = [
        (element_type, getattr(element, "name", ""))
        for element_type, element in candidates
        if getattr(element, "name", "")
    ]
    if not available:
        available = _layout_element_names_from_parent(layout)
    available_text = ", ".join(f"{element_type}:{name}" for element_type, name in available)
    detail = f" Available layout elements: {available_text}" if available_text else ""
    raise RuntimeError(f"Layout element not found: {element_name}.{detail}")


def _layout_elements(parent: Any) -> list[tuple[str, Any]]:
    candidates = []
    for element_type in _LAYOUT_ELEMENT_TYPES:
        try:
            elements = parent.listElements(element_type)
        except (TypeError, ValueError):
            continue
        for element in elements:
            candidates.append((element_type, element))
            if element_type == "GROUP_ELEMENT" and hasattr(element, "listElements"):
                candidates.extend(_layout_elements(element))
    return candidates


def _layout_element_names_from_parent(parent: Any) -> list[tuple[str, str]]:
    return [
        (element_type, getattr(element, "name", ""))
        for element_type, element in _layout_elements(parent)
        if getattr(element, "name", "")
    ]


def _normalized_layout_name(value: str) -> str:
    return "".join(value.split()).casefold()


def _layout_element_xy(
    layout: Any,
    element: Any,
    position: LayoutElementPosition,
) -> tuple[float, float]:
    if position.anchor is None:
        if position.x is None or position.y is None:
            raise ValueError("Absolute layout element positions require both x and y.")
        return position.x + position.offset_x, position.y + position.offset_y

    page_width = _layout_number(layout, "pageWidth")
    page_height = _layout_number(layout, "pageHeight")
    element_width = _layout_number(element, "elementWidth")
    element_height = _layout_number(element, "elementHeight")

    if position.anchor == "bottom_left":
        x, y = 0.0, 0.0
    elif position.anchor == "bottom_center":
        x, y = (page_width - element_width) / 2, 0.0
    elif position.anchor == "bottom_right":
        x, y = page_width - element_width, 0.0
    elif position.anchor == "middle_left":
        x, y = 0.0, (page_height - element_height) / 2
    elif position.anchor == "center":
        x, y = (page_width - element_width) / 2, (page_height - element_height) / 2
    elif position.anchor == "middle_right":
        x, y = page_width - element_width, (page_height - element_height) / 2
    elif position.anchor == "top_left":
        x, y = 0.0, page_height - element_height
    elif position.anchor == "top_center":
        x, y = (page_width - element_width) / 2, page_height - element_height
    elif position.anchor == "top_right":
        x, y = page_width - element_width, page_height - element_height
    else:
        raise ValueError(f"Unsupported layout element anchor: {position.anchor}")

    return x + position.offset_x, y + position.offset_y


def _layout_number(element: Any, attribute: str) -> float:
    value = getattr(element, attribute, None)
    if not isinstance(value, (int, float)) or not math.isfinite(value):
        raise RuntimeError(f"Layout element is missing numeric {attribute}.")
    return float(value)


def _set_layout_element_bottom_left_anchor(element: Any) -> None:
    if not hasattr(element, "setAnchor"):
        return
    try:
        element.setAnchor("BOTTOM_LEFT_CORNER")
    except Exception:
        pass


def _apply_extent(arcpy: Any, layout: Any, map_obj: Any, request: RenderPreviewRequest) -> None:
    map_frame = _first_or_named_map_frame(layout, request.project.export.map_frame_name)

    extent = request.project.extent
    if extent is not None:
        arcpy_extent = arcpy.Extent(extent.xmin, extent.ymin, extent.xmax, extent.ymax)
        if extent.spatial_reference_wkid:
            try:
                arcpy_extent.spatialReference = arcpy.SpatialReference(extent.spatial_reference_wkid)
            except Exception:
                pass
        map_frame.camera.setExtent(arcpy_extent)
        return

    if request.project.fit_to_layers:
        _fit_map_frame_to_layers(arcpy, map_frame, map_obj, request)


def _first_or_named_map_frame(layout: Any, name: Optional[str] = None) -> Any:
    frames = layout.listElements("MAPFRAME_ELEMENT", name or "*")
    if not frames:
        raise RuntimeError("No map frame was found in the selected layout.")
    return frames[0]


def _fit_map_frame_to_layers(
    arcpy: Any,
    map_frame: Any,
    map_obj: Any,
    request: RenderPreviewRequest,
) -> None:
    target_names = {name for name in request.project.fit_layer_names if name}
    combined = None
    spatial_reference = None

    for layer in map_obj.listLayers():
        if target_names:
            if getattr(layer, "name", "") not in target_names:
                continue
        elif not getattr(layer, "visible", True):
            continue

        extent = _layer_extent(map_frame, layer)
        if extent is None or not _is_valid_extent(extent):
            continue

        combined = _combine_extents(arcpy, combined, extent)
        spatial_reference = spatial_reference or getattr(extent, "spatialReference", None)

    if combined is None:
        detail = ", ".join(sorted(target_names)) if target_names else "visible layers"
        raise RuntimeError(f"Could not calculate an extent for {detail}.")

    padded = _pad_extent(arcpy, combined, request.project.fit_padding)
    if spatial_reference:
        try:
            padded.spatialReference = spatial_reference
        except Exception:
            pass
    map_frame.camera.setExtent(padded)


def _layer_extent(map_frame: Any, layer: Any) -> Optional[Any]:
    try:
        return map_frame.getLayerExtent(layer, False, True)
    except Exception:
        return None


def _is_valid_extent(extent: Any) -> bool:
    values = _extent_values(extent)
    return (
        all(math.isfinite(value) for value in values)
        and values[0] <= values[2]
        and values[1] <= values[3]
    )


def _combine_extents(arcpy: Any, current: Optional[Any], extent: Any) -> Any:
    if current is None:
        xmin, ymin, xmax, ymax = _extent_values(extent)
    else:
        current_xmin, current_ymin, current_xmax, current_ymax = _extent_values(current)
        extent_xmin, extent_ymin, extent_xmax, extent_ymax = _extent_values(extent)
        xmin = min(current_xmin, extent_xmin)
        ymin = min(current_ymin, extent_ymin)
        xmax = max(current_xmax, extent_xmax)
        ymax = max(current_ymax, extent_ymax)
    return arcpy.Extent(xmin, ymin, xmax, ymax)


def _pad_extent(arcpy: Any, extent: Any, padding: float) -> Any:
    xmin, ymin, xmax, ymax = _extent_values(extent)
    width = xmax - xmin
    height = ymax - ymin
    fallback_size = max(abs(xmin), abs(ymin), abs(xmax), abs(ymax), 1.0) * 0.0001

    if width == 0:
        xmin -= fallback_size
        xmax += fallback_size
        width = xmax - xmin
    if height == 0:
        ymin -= fallback_size
        ymax += fallback_size
        height = ymax - ymin

    return arcpy.Extent(
        xmin - width * padding,
        ymin - height * padding,
        xmax + width * padding,
        ymax + height * padding,
    )


def _extent_values(extent: Any) -> tuple[float, float, float, float]:
    return (
        float(extent.XMin),
        float(extent.YMin),
        float(extent.XMax),
        float(extent.YMax),
    )


def _export_layout(layout: Any, request: RenderPreviewRequest, output_dir: Path) -> Path:
    export_format = request.project.export.format
    dpi = request.project.export.dpi

    if export_format == "png":
        path = output_dir / "preview.png"
        layout.exportToPNG(str(path), resolution=dpi)
        return path
    if export_format == "jpg":
        path = output_dir / "preview.jpg"
        layout.exportToJPEG(str(path), resolution=dpi)
        return path
    if export_format == "pdf":
        path = output_dir / "preview.pdf"
        layout.exportToPDF(str(path), resolution=dpi)
        return path

    raise ValueError(f"Unsupported export format: {export_format}")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run one ArcPy render job.")
    parser.add_argument("--job-id", required=True)
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--result", required=True, type=Path)
    return parser.parse_args()


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.agents.cartography.skills.cartographic_standards.schema import (
    CartographicStandardsPolicy,
    LayoutElementPositionOperation,
    TextStyleOperation,
)


@lru_cache(maxsize=1)
def load_cartographic_standards_policy() -> CartographicStandardsPolicy:
    path = Path(__file__).with_name("policy.json")
    return CartographicStandardsPolicy.model_validate_json(path.read_text(encoding="utf-8"))


def build_text_styles_from_request(
    message: str,
    policy: CartographicStandardsPolicy | None = None,
) -> list[dict[str, Any]]:
    policy = policy or load_cartographic_standards_policy()
    if not _mentions_title(message):
        return []

    operation: dict[str, Any] = {"element_name": policy.title_element_name}
    font_family = _extract_font_family(message, policy)
    font_size = _extract_font_size(message)
    font_style = _extract_font_style(message, policy)

    if font_family is not None:
        operation["font_family"] = font_family
    if font_size is not None:
        operation["font_size"] = font_size
    if font_style is not None:
        operation["font_style"] = font_style

    if len(operation) == 1:
        return []
    return [TextStyleOperation(**operation).model_dump(exclude_none=True)]


def build_layout_element_positions_from_request(
    message: str,
    policy: CartographicStandardsPolicy | None = None,
) -> list[dict[str, Any]]:
    policy = policy or load_cartographic_standards_policy()
    positions = []
    aliases = tuple(policy.layout_element_aliases.keys())
    for alias, element_name in policy.layout_element_aliases.items():
        position = _extract_position_for_alias(message, alias, aliases, policy)
        if position is None:
            continue
        operation = LayoutElementPositionOperation(element_name=element_name, **position)
        positions.append(_layout_position_dump(operation))
    return _dedupe_layout_positions(positions)


def apply_cartographic_standards_to_tool_calls(
    message: str,
    tool_calls: list[dict[str, Any]],
    policy: CartographicStandardsPolicy | None = None,
) -> list[dict[str, Any]]:
    policy = policy or load_cartographic_standards_policy()
    text_styles = build_text_styles_from_request(message, policy)
    layout_elements = build_layout_element_positions_from_request(message, policy)
    layout_operations = build_layout_operations_from_request(message, policy)
    if not text_styles and not layout_elements and not layout_operations:
        return tool_calls

    updated_calls = []
    for tool_call in tool_calls:
        if tool_call.get("name") != "run_arcpy_code":
            updated_calls.append(tool_call)
            continue
        arguments = dict(tool_call.get("arguments") or {})
        if text_styles:
            arguments["text_styles"] = _merge_by_element_name(
                arguments.get("text_styles"),
                text_styles,
            )
        if layout_elements:
            arguments["layout_elements"] = _merge_by_element_name(
                arguments.get("layout_elements"),
                layout_elements,
            )
        if layout_operations:
            arguments["layout_operations"] = _merge_layout_operations(
                arguments.get("layout_operations"),
                layout_operations,
            )
        updated_calls.append({**tool_call, "arguments": arguments})
    return updated_calls


def build_layout_operations_from_request(
    message: str,
    policy: CartographicStandardsPolicy | None = None,
) -> list[dict[str, Any]]:
    policy = policy or load_cartographic_standards_policy()
    operations: list[dict[str, Any]] = []

    if _requests_layout_creation(message):
        for alias, _element_name, operation_type, default_name in _SURROUND_OPERATION_ALIASES:
            if alias.lower() not in message.lower():
                continue
            position = _extract_position_for_alias(
                message,
                alias,
                _ALL_OPERATION_ALIASES,
                policy,
            )
            operation: dict[str, Any] = {"type": operation_type, "name": default_name}
            if position is not None:
                operation.update(position)
            operations.append(operation)

    for alias in _GRID_ALIASES:
        if alias.lower() in message.lower():
            operations.append({"type": "ensure_grid"})
            break

    for alias in _INSET_ALIASES:
        if alias.lower() not in message.lower():
            continue
        position = _extract_position_for_alias(message, alias, _ALL_OPERATION_ALIASES, policy)
        operation = {"type": "ensure_inset_map", "name": "Inset Map Frame"}
        if position is not None:
            operation.update(position)
        operations.append(operation)
        break

    return _dedupe_layout_operations(operations)


def _layout_position_dump(operation: LayoutElementPositionOperation) -> dict[str, Any]:
    payload = operation.model_dump(exclude_none=True)
    if payload.get("offset_x") == 0.0:
        payload.pop("offset_x", None)
    if payload.get("offset_y") == 0.0:
        payload.pop("offset_y", None)
    return payload


def _merge_by_element_name(
    existing: Any,
    additions: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    if isinstance(existing, list):
        for item in existing:
            if isinstance(item, dict) and isinstance(item.get("element_name"), str):
                merged[_style_key(item["element_name"])] = dict(item)

    for item in additions:
        key = _style_key(str(item["element_name"]))
        merged[key] = {**merged.get(key, {}), **item}
    return list(merged.values())


def _merge_layout_operations(
    existing: Any,
    additions: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    merged: dict[tuple[str, str], dict[str, Any]] = {}
    if isinstance(existing, list):
        for item in existing:
            if isinstance(item, dict) and isinstance(item.get("type"), str):
                key = _layout_operation_key(item)
                merged[key] = dict(item)

    for item in additions:
        key = _layout_operation_key(item)
        merged[key] = {**merged.get(key, {}), **item}
    return list(merged.values())


def _dedupe_layout_operations(operations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: dict[tuple[str, str], dict[str, Any]] = {}
    for operation in operations:
        key = _layout_operation_key(operation)
        merged[key] = {**merged.get(key, {}), **operation}
    return list(merged.values())


def _layout_operation_key(operation: dict[str, Any]) -> tuple[str, str]:
    return (
        str(operation.get("type") or "").strip().lower(),
        str(operation.get("name") or "").strip().casefold(),
    )


def _requests_layout_creation(message: str) -> bool:
    lowered = message.lower()
    return any(keyword in lowered for keyword in _LAYOUT_CREATION_KEYWORDS)


_LAYOUT_CREATION_KEYWORDS = (
    "\u6dfb\u52a0",
    "\u52a0\u4e0a",
    "\u52a0\u4e00\u4e2a",
    "\u63d2\u5165",
    "\u521b\u5efa",
    "\u751f\u6210",
    "\u5e26\u6709",
    "\u5305\u542b",
    "\u9700\u8981",
    "add",
    "insert",
    "create",
    "ensure",
    "include",
    "with",
)
_SURROUND_OPERATION_ALIASES: tuple[tuple[str, str, str, str], ...] = (
    ("\u6bd4\u4f8b\u5c3a", "\u6bd4\u4f8b\u5c3a", "ensure_scale_bar", "\u6bd4\u4f8b\u5c3a"),
    ("scale bar", "\u6bd4\u4f8b\u5c3a", "ensure_scale_bar", "\u6bd4\u4f8b\u5c3a"),
    ("scalebar", "\u6bd4\u4f8b\u5c3a", "ensure_scale_bar", "\u6bd4\u4f8b\u5c3a"),
    ("\u6307\u5317\u9488", "zbz", "ensure_north_arrow", "zbz"),
    ("\u5317\u7bad\u5934", "zbz", "ensure_north_arrow", "zbz"),
    ("north arrow", "zbz", "ensure_north_arrow", "zbz"),
)
_GRID_ALIASES = (
    "\u683c\u7f51",
    "\u7ecf\u7eac\u7f51",
    "grid",
    "graticule",
)
_INSET_ALIASES = (
    "\u5c0f\u56fe",
    "\u63d2\u56fe",
    "\u9e70\u773c\u56fe",
    "inset map",
    "inset",
    "overview map",
)
_ALL_OPERATION_ALIASES = tuple(
    [alias for alias, _, _, _ in _SURROUND_OPERATION_ALIASES]
    + list(_GRID_ALIASES)
    + list(_INSET_ALIASES)
)

_ANCHOR_PATTERNS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("bottom_left", ("左下角", "左下", "lower left", "bottom left")),
    ("bottom_right", ("右下角", "右下", "lower right", "bottom right")),
    ("top_left", ("左上角", "左上", "upper left", "top left")),
    ("top_right", ("右上角", "右上", "upper right", "top right")),
    ("bottom_center", ("下方居中", "底部居中", "底端居中", "bottom center")),
    ("top_center", ("上方居中", "顶部居中", "顶端居中", "top center")),
    ("middle_left", ("左侧居中", "左边居中", "左中", "middle left")),
    ("middle_right", ("右侧居中", "右边居中", "右中", "middle right")),
    ("center", ("页面中间", "版面中间", "正中间", "居中", "center")),
)

_OFFSET_PATTERNS: tuple[tuple[str, float, tuple[str, ...]], ...] = (
    ("offset_y", 1.0, ("往上", "向上", "上移", "上移动", "move up", "up")),
    ("offset_y", -1.0, ("往下", "向下", "下移", "下移动", "move down", "down")),
    ("offset_x", 1.0, ("往右", "向右", "右移", "右移动", "move right", "right")),
    ("offset_x", -1.0, ("往左", "向左", "左移", "左移动", "move left", "left")),
)

_UNIT_ALIASES = {
    "毫米": "millimeter",
    "mm": "millimeter",
    "millimeter": "millimeter",
    "millimeters": "millimeter",
    "厘米": "centimeter",
    "cm": "centimeter",
    "centimeter": "centimeter",
    "centimeters": "centimeter",
    "英寸": "inch",
    "inch": "inch",
    "inches": "inch",
    "in": "inch",
}

_UNIT_TO_INCH = {
    "inch": 1.0,
    "centimeter": 1.0 / 2.54,
    "millimeter": 1.0 / 25.4,
}


def _extract_position_for_alias(
    message: str,
    alias: str,
    aliases: tuple[str, ...],
    policy: CartographicStandardsPolicy,
) -> dict[str, Any] | None:
    lowered = message.lower()
    alias_index = lowered.find(alias.lower())
    if alias_index < 0:
        return None

    window = _alias_window(message, alias_index, alias, aliases)
    xy_match = re.search(
        r"(?i)\bx\s*[=:：]?\s*([0-9]+(?:\.[0-9]+)?)\D{0,20}\by\s*[=:：]?\s*([0-9]+(?:\.[0-9]+)?)",
        window,
    )
    if xy_match:
        return {
            "x": float(xy_match.group(1)),
            "y": float(xy_match.group(2)),
            "units": policy.default_position_units,
        }

    anchor = _extract_anchor(window)
    if anchor is not None:
        offset_x, offset_y, units = _extract_offsets(window, policy.default_position_units)
        position: dict[str, Any] = {"anchor": anchor, "units": units}
        if offset_x:
            position["offset_x"] = offset_x
        if offset_y:
            position["offset_y"] = offset_y
        return position

    position_words = ("位置", "坐标", "放到", "放在", "移到", "移动到", "position")
    if not any(word in window.lower() for word in position_words):
        return None
    numbers = re.findall(r"(?<![A-Za-z0-9])([0-9]+(?:\.[0-9]+)?)(?![A-Za-z0-9])", window)
    if len(numbers) >= 2:
        return {
            "x": float(numbers[0]),
            "y": float(numbers[1]),
            "units": policy.default_position_units,
        }
    return None


def _alias_window(
    message: str,
    alias_index: int,
    alias: str,
    aliases: tuple[str, ...],
) -> str:
    lowered = message.lower()
    search_from = alias_index + len(alias)
    end = min(len(message), alias_index + 140)
    for other_alias in aliases:
        if other_alias == alias:
            continue
        other_index = lowered.find(other_alias.lower(), search_from)
        if search_from <= other_index < end:
            end = other_index
    return message[alias_index:end]


def _extract_anchor(window: str) -> str | None:
    lowered = window.lower()
    for anchor, patterns in _ANCHOR_PATTERNS:
        if any(pattern in window or pattern in lowered for pattern in patterns):
            return anchor
    return None


def _extract_offsets(window: str, default_units: str) -> tuple[float, float, str]:
    raw_offsets: list[tuple[str, float, str | None]] = []
    for axis, sign, direction_patterns in _OFFSET_PATTERNS:
        direction_regex = "|".join(re.escape(pattern) for pattern in direction_patterns)
        pattern = (
            rf"(?i)(?:{direction_regex})\s*(?:移动)?\s*"
            r"([0-9]+(?:\.[0-9]+)?)\s*"
            r"(毫米|mm|millimeters?|厘米|cm|centimeters?|英寸|inches?|in)?"
        )
        for match in re.finditer(pattern, window):
            unit = _normalize_unit(match.group(2))
            raw_offsets.append((axis, sign * float(match.group(1)), unit))

    units = next((unit for _, _, unit in raw_offsets if unit is not None), default_units)
    offset_x = 0.0
    offset_y = 0.0
    for axis, value, value_units in raw_offsets:
        converted = _convert_position_value(value, value_units or units, units)
        if axis == "offset_x":
            offset_x += converted
        else:
            offset_y += converted
    return offset_x, offset_y, units


def _normalize_unit(unit: str | None) -> str | None:
    if unit is None:
        return None
    return _UNIT_ALIASES.get(unit.strip().lower())


def _convert_position_value(value: float, from_units: str, to_units: str) -> float:
    if from_units == to_units:
        return value
    return value * _UNIT_TO_INCH[from_units] / _UNIT_TO_INCH[to_units]


def _dedupe_layout_positions(positions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped: dict[str, dict[str, Any]] = {}
    for position in positions:
        deduped[_style_key(str(position["element_name"]))] = position
    return list(deduped.values())


def _mentions_title(message: str) -> bool:
    lowered = message.lower()
    return any(pattern in message or pattern in lowered for pattern in ("标题", "题名", "图名", "title"))


def _extract_font_family(
    message: str,
    policy: CartographicStandardsPolicy,
) -> str | None:
    lowered = message.lower()
    for alias, canonical in policy.font_family_aliases.items():
        if alias in message or alias.lower() in lowered:
            return canonical

    match = re.search(
        r"(?i)(?:font(?:\s*family)?|字体)\s*(?:为|是|:|：)?\s*([A-Za-z][A-Za-z0-9 ]{1,60})",
        message,
    )
    if match:
        return " ".join(match.group(1).split()).strip(" ,，。.")
    return None


def _extract_font_size(message: str) -> float | None:
    patterns = (
        r"(?:字号|字体大小|textSize|font\s*size)\s*(?:为|是|:|：)?\s*([0-9]+(?:\.[0-9]+)?)",
        r"([0-9]+(?:\.[0-9]+)?)\s*(?:号字|pt|磅)",
    )
    for pattern in patterns:
        match = re.search(pattern, message, flags=re.IGNORECASE)
        if match:
            return float(match.group(1))
    return None


def _extract_font_style(
    message: str,
    policy: CartographicStandardsPolicy,
) -> str | None:
    lowered = message.lower()
    for alias, canonical in policy.font_style_aliases.items():
        if alias in message or alias.lower() in lowered:
            return canonical
    return None


def _style_key(element_name: str) -> str:
    return "".join(element_name.split()).casefold()

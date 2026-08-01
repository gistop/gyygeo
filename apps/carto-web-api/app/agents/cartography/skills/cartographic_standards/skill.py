from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.agents.cartography.skills.cartographic_standards.schema import (
    CartographicStandardsPolicy,
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


def apply_cartographic_standards_to_tool_calls(
    message: str,
    tool_calls: list[dict[str, Any]],
    policy: CartographicStandardsPolicy | None = None,
) -> list[dict[str, Any]]:
    text_styles = build_text_styles_from_request(message, policy)
    if not text_styles:
        return tool_calls

    updated_calls = []
    for tool_call in tool_calls:
        if tool_call.get("name") != "run_arcpy_code":
            updated_calls.append(tool_call)
            continue
        arguments = dict(tool_call.get("arguments") or {})
        arguments["text_styles"] = _merge_text_styles(
            arguments.get("text_styles"),
            text_styles,
        )
        updated_calls.append({**tool_call, "arguments": arguments})
    return updated_calls


def _merge_text_styles(
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

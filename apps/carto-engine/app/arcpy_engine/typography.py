from __future__ import annotations

from typing import Any

from app.schemas.project import TextTypography


def apply_text_typography_operations(
    layout: Any,
    styles: list[TextTypography],
) -> list[str]:
    messages = []
    for style in styles:
        element = _find_text_element(layout, style.element_name)
        if element is None:
            if style.required:
                raise RuntimeError(f"Text element not found for typography: {style.element_name}")
            messages.append(f"Text element not found for typography: {style.element_name}")
            continue

        if style.font_size is not None:
            element.textSize = float(style.font_size)
        if style.font_family is not None:
            element.fontFamilyName = style.font_family
        if style.font_style is not None:
            element.fontStyleName = style.font_style

        applied = []
        if style.font_family is not None:
            applied.append(f"font_family={style.font_family}")
        if style.font_size is not None:
            applied.append(f"font_size={style.font_size:g}")
        if style.font_style is not None:
            applied.append(f"font_style={style.font_style}")
        messages.append(f"Applied typography to text element {style.element_name}: {', '.join(applied)}")
    return messages


def _find_text_element(layout: Any, element_name: str) -> Any | None:
    matches = layout.listElements("TEXT_ELEMENT", element_name)
    if matches:
        return matches[0]

    target = _normalized_layout_name(element_name)
    for element in layout.listElements("TEXT_ELEMENT"):
        if _normalized_layout_name(getattr(element, "name", "")) == target:
            return element
    return None


def _normalized_layout_name(value: str) -> str:
    return "".join(value.split()).casefold()

# ArcPy Layout Text

Verified fact for ArcPy `3.6.1` in this workspace:

- `createTextElement` exists on `ArcGISProject`.
- `createTextElement` does not exist on `Layout`.
- `createMapTitle` is not available on `Layout` or `MapFrame`.

Use this API to create layout text:

```python
title = aprx.createTextElement(
    layout,
    arcpy.Point(x, y),
    "POINT",
    "Map title text",
    text_size=24,
    font_family_name="Microsoft YaHei UI",
    font_style_name="Bold",
    name="Title",
)
```

Important: the third positional argument is a geometry text type, not a semantic role. For map
titles, still pass `"POINT"` as `text_type`; never pass `"TITLE"` or `"TEXT"` there.

After creating point text, set a center anchor if the text should be centered:

```python
title.setAnchor("CENTER_POINT")
title.elementPositionX = float(layout.pageWidth) / 2
title.elementPositionY = float(layout.pageHeight) - 0.35
```

Do not use:

```python
layout.createTextElement(...)
layout.createMapTitle(...)
map_frame.createMapTitle(...)
createMapTitle(...)
aprx.createTextElement(title_text, "TEXT", "Title", (x, y))
aprx.createTextElement(layout, point, "TITLE", title_text)
aprx.createTextElement(layout, point, "TEXT", title_text)
```

To update an existing title only when it exists:

```python
matches = layout.listElements("TEXT_ELEMENT", "Title")
if matches:
    matches[0].text = "New title"
else:
    point = arcpy.Point(float(layout.pageWidth) / 2, float(layout.pageHeight) - 0.35)
    title = aprx.createTextElement(layout, point, "POINT", "New title", text_size=24, name="Title")
    title.setAnchor("CENTER_POINT")
```

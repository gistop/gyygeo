# ArcPy Layout Elements

Layout elements should be inspected by type and name:

```python
layout.listElements("MAPFRAME_ELEMENT")
layout.listElements("MAPSURROUND_ELEMENT")
layout.listElements("TEXT_ELEMENT")
```

The default template currently has a north arrow named `zbz`.

Move an existing element:

```python
north_arrow = layout.listElements("MAPSURROUND_ELEMENT", "zbz")[0]
north_arrow.elementPositionX = 11.8
north_arrow.elementPositionY = 7.8
```

Use element names exactly when possible. If a requested element might not exist, check first and
raise a clear error:

```python
matches = layout.listElements("MAPSURROUND_ELEMENT", "zbz")
if not matches:
    raise RuntimeError("North arrow element not found: zbz")
north_arrow = matches[0]
```

Common anchors:

- `BOTTOM_LEFT_CORNER`
- `BOTTOM_RIGHT_CORNER`
- `TOP_LEFT_CORNER`
- `TOP_RIGHT_CORNER`
- `CENTER_POINT`

Set an anchor before positioning when precise placement matters:

```python
north_arrow.setAnchor("BOTTOM_LEFT_CORNER")
north_arrow.elementPositionX = 0.3
north_arrow.elementPositionY = 0.3
```

# ArcPy Layout Elements

Layout elements should be inspected by type and name:

```python
layout.listElements("MAPFRAME_ELEMENT")
layout.listElements("MAPSURROUND_ELEMENT")
layout.listElements("TEXT_ELEMENT")
```

The default template currently has a north arrow named `zbz`.

For generated expert tool calls, use `layout_operations` for standard map surrounds:

- `ensure_scale_bar`
- `ensure_north_arrow`
- `ensure_grid`
- `ensure_inset_map`

If one of these operations is present in `layout_operations`, do not hand-write helper functions
or direct ArcPy calls for the same operation in `run_arcpy_code`. The carto-engine applies these
operations after the base script succeeds.

Hard constraints:

- Do not call `map_frame.createMapGrid(...)`; ArcGIS Pro `MapFrame` does not provide this method.
- Do not call `map_frame.addGrid(...)` or `map_frame.addMapGrid(...)` from generated expert code.
- For map grids or graticules, add `{"type": "ensure_grid"}` to `layout_operations` and let
  carto-engine create the grid with the verified style workflow.

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

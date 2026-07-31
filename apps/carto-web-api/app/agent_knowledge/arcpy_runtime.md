# ArcPy Runtime Facts

Verified runtime:

- ArcGIS Pro / ArcPy version: `3.6.1`
- Expert code is executed by `carto-engine`, not by `carto-web-api`.
- `carto-engine` copies the APRX template before running generated code.
- Generated code runs as a full Python script with these injected variables:
  - `APRX_PATH`: path to the copied APRX workspace.
  - `OUTPUT_DIR`: `pathlib.Path` for the job output directory.
  - `OUTPUT_PATH`: target export path.
  - `DPI`: export resolution.
  - `CONTEXT`: JSON-compatible dict from the web page and agent.
- When present, `CONTEXT["prepared_dataset_path"]` is the local GeoTIFF prepared from the left-side
  data panel. Add it to the first map with `map_obj.addDataFromPath(...)` before exporting unless
  the user explicitly asks for a layout-only change.
- After adding `CONTEXT["prepared_dataset_path"]`, zoom the layout map frame to that layer's extent
  with `map_frame.getLayerExtent(...)` and `map_frame.camera.setExtent(...)`. Add about `0.08`
  proportional padding around the extent, matching the standard render workflow's `fit_padding`.

Required output contract:

- The script must create `OUTPUT_PATH`.
- The script should call `aprx.save()` after APRX modifications.
- The script should delete the project reference at the end with `del aprx`.

Basic pattern:

```python
import arcpy

aprx = arcpy.mp.ArcGISProject(APRX_PATH)
layout = aprx.listLayouts()[0]
map_obj = aprx.listMaps()[0]

prepared_dataset_path = CONTEXT.get("prepared_dataset_path")
if prepared_dataset_path:
    added_layer = map_obj.addDataFromPath(prepared_dataset_path)
    if hasattr(added_layer, "name"):
        added_layer.name = "Prepared Remote Sensing Basemap"

    map_frame = layout.listElements("MAPFRAME_ELEMENT")[0]
    layer_extent = map_frame.getLayerExtent(added_layer, False, True)
    padding = 0.08
    x_padding = (float(layer_extent.XMax) - float(layer_extent.XMin)) * padding
    y_padding = (float(layer_extent.YMax) - float(layer_extent.YMin)) * padding
    padded_extent = arcpy.Extent(
        float(layer_extent.XMin) - x_padding,
        float(layer_extent.YMin) - y_padding,
        float(layer_extent.XMax) + x_padding,
        float(layer_extent.YMax) + y_padding,
    )
    if getattr(layer_extent, "spatialReference", None):
        try:
            padded_extent.spatialReference = layer_extent.spatialReference
        except Exception:
            pass
    map_frame.camera.setExtent(padded_extent)

# Modify APRX here.

aprx.save()
layout.exportToJPEG(OUTPUT_PATH, resolution=DPI)
del aprx
```

Avoid:

- Do not assume a text element named `Title` already exists.
- Do not use undefined paths. Use the injected `APRX_PATH`, `OUTPUT_DIR`, and `OUTPUT_PATH`.
- Do not write output to an arbitrary hard-coded path.

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

# Modify APRX here.

aprx.save()
layout.exportToJPEG(OUTPUT_PATH, resolution=DPI)
del aprx
```

Avoid:

- Do not assume a text element named `Title` already exists.
- Do not use undefined paths. Use the injected `APRX_PATH`, `OUTPUT_DIR`, and `OUTPUT_PATH`.
- Do not write output to an arbitrary hard-coded path.

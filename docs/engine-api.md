# carto-engine API

Base URL for local development:

```text
http://127.0.0.1:8000
```

## Health

```http
GET /health
```

Returns basic service status without importing ArcPy.

## Runtime

```http
GET /runtime
```

Returns ArcPy availability and runtime details. This endpoint can be slower because it starts a Python subprocess and imports ArcPy.

## Create Preview Render Job

```http
POST /api/v1/render/preview
Content-Type: application/json
```

Example:

```json
{
  "requested_by": "local-dev",
  "dry_run": true,
  "project": {
    "project_name": "demo-map",
    "template_id": "default",
    "title": "Demo Map",
    "remove_layers": [],
    "layers": [],
    "fit_to_layers": false,
    "export": {
      "format": "png",
      "dpi": 150
    }
  }
}
```

Response status is `202 Accepted`. Poll the returned job ID.

### Known Working GeoTIFF Example

This example renders the prepared data-service GeoTIFF through the default template. The template
layout is named `布局`, so the request must use that exact `layout_name`.

```json
{
  "requested_by": "local-dev",
  "dry_run": false,
  "project": {
    "project_name": "landsat-map",
    "template_id": "default",
    "title": "Landsat Map",
    "layers": [
      {
        "id": "landsat-raster",
        "name": "Landsat Raster",
        "data_source": "C:\\Users\\Administrator\\gyygeo\\apps\\data-service\\cache\\prepared\\ds_98f7772650d74a9ebdb89788a8ae23f9.tif",
        "visible": true,
        "opacity": 1.0
      }
    ],
    "fit_to_layers": true,
    "fit_layer_names": ["Landsat Raster"],
    "export": {
      "format": "png",
      "dpi": 150,
      "layout_name": "布局"
    }
  }
}
```

### Layer Removal and Auto Fit

`remove_layers` removes existing template layers by exact layer name before new layers are added.

`fit_to_layers` automatically sets the selected layout map frame extent after layer changes. If `extent`
is provided, that explicit extent wins and auto fit is skipped.

When `fit_layer_names` is empty, auto fit uses all visible layers in the map. When `fit_layer_names`
contains names, auto fit uses only those named layers. `fit_padding` adds proportional padding around
the combined layer extent; the default is `0.08`.

Example:

```json
{
  "requested_by": "local-dev",
  "dry_run": false,
  "project": {
    "project_name": "roads-map",
    "template_id": "default",
    "remove_layers": ["Old Roads"],
    "layers": [
      {
        "id": "new-roads",
        "name": "New Roads",
        "data_source": "C:\\data\\roads.shp",
        "visible": true,
        "opacity": 1.0
      }
    ],
    "fit_to_layers": true,
    "fit_layer_names": ["New Roads"],
    "fit_padding": 0.08,
    "export": {
      "format": "png",
      "dpi": 150,
      "layout_name": "布局"
    }
  }
}
```

### Layout Page Size

`page` changes the selected layout page before layout text, layout element positioning, map-frame
fitting, and export. Named page sizes are converted into the selected ArcGIS layout's current
`pageUnits`.

Supported named sizes:

- `a0`
- `a1`
- `a2`
- `a3`
- `a4`
- `letter`
- `legal`

Supported orientations:

- `portrait`
- `landscape`

Example: render an A4 landscape output without resizing existing layout elements.

```json
{
  "requested_by": "local-dev",
  "dry_run": false,
  "project": {
    "project_name": "a4-landscape-demo",
    "template_id": "default",
    "page": {
      "size": "a4",
      "orientation": "landscape",
      "resize_elements": false
    },
    "export": {
      "format": "png",
      "dpi": 150
    }
  }
}
```

Custom page sizes can use `millimeter`, `centimeter`, or `inch`:

```json
{
  "project": {
    "project_name": "custom-page-demo",
    "page": {
      "width": 11,
      "height": 8.5,
      "units": "inch"
    }
  }
}
```

### Layout Element Positions

`layout_elements` moves existing layout elements by exact element name. Positions can use absolute
page coordinates (`x` and `y`) or a page anchor plus optional offsets. Page coordinates use the
ArcGIS layout page units from the template.

Supported anchors:

- `bottom_left`
- `bottom_center`
- `bottom_right`
- `middle_left`
- `center`
- `middle_right`
- `top_left`
- `top_center`
- `top_right`

Example: move an existing north arrow element named `zbz` to the lower-left corner with a small inset.

```json
{
  "requested_by": "local-dev",
  "dry_run": false,
  "project": {
    "project_name": "layout-element-demo",
    "template_id": "default",
    "layout_elements": [
      {
        "element_name": "zbz",
        "anchor": "bottom_left",
        "offset_x": 0.3,
        "offset_y": 0.3
      }
    ],
    "export": {
      "format": "png",
      "dpi": 150,
      "layout_name": "甯冨眬"
    }
  }
}
```

## Create ArcPy Code Job

```http
POST /api/v1/arcpy/code
Content-Type: application/json
```

This endpoint runs a complete ArcPy Python script against a copied APRX template. It is intended for
expert/agent-generated code experiments. The engine injects these variables before the submitted
code runs:

- `APRX_PATH`
- `OUTPUT_DIR`
- `OUTPUT_PATH`
- `DPI`
- `CONTEXT`

The submitted code must create `OUTPUT_PATH`.

Example:

```json
{
  "requested_by": "gyygeo-expert-agent",
  "project_name": "expert-title-demo",
  "template_id": "default",
  "output_format": "jpg",
  "dpi": 300,
  "context": {
    "map_title": "Expert Title Demo"
  },
  "code": "import arcpy\naprx = arcpy.mp.ArcGISProject(APRX_PATH)\nlayout = aprx.listLayouts()[0]\npoint = arcpy.Point(float(layout.pageWidth) / 2, float(layout.pageHeight) - 0.35)\naprx.createTextElement(layout, point, \"POINT\", \"Expert Title Demo\", text_size=24, name=\"Title\")\naprx.save()\nlayout.exportToJPEG(OUTPUT_PATH, resolution=DPI)\ndel aprx"
}
```

Response status is `202 Accepted`. Poll the returned job ID through `GET /api/v1/jobs/{job_id}`.

## Get Job

```http
GET /api/v1/jobs/{job_id}
```

Job statuses:

- `pending`
- `running`
- `done`
- `failed`

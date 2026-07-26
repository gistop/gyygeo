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

## Get Job

```http
GET /api/v1/jobs/{job_id}
```

Job statuses:

- `pending`
- `running`
- `done`
- `failed`

# Research Area Overview Map Agent

This is the first formal map-making agent workflow for `gyygeo`.

## Scope

The initial workflow creates a research-area overview map using remote-sensing imagery as the
basemap. It is intentionally narrow and production-shaped:

- Use the current map AOI as the confirmed study-area boundary.
- Search remote-sensing imagery through `data-service`.
- Select a candidate image by lowest cloud cover.
- Prepare a render-ready raster through `data-service` using MPC dynamic tiles by default, so the
  workflow reads only tiles needed for the AOI instead of downloading full COG assets.
- Write a study-area boundary GeoJSON.
- Render a map through `carto-engine`.
- Run basic QA checks and return output paths.

## Agent Entry Points

- `POST /api/v1/agent/chat`
- `GET /api/v1/agent/tasks/{task_id}`

The chat endpoint starts an agent task when the user asks for a research-area overview map. The
task endpoint returns structured progress, tool outputs, QA results, and errors.

## Map Spec

Each task owns a structured `map_spec`:

```json
{
  "schema_version": "0.1",
  "map_kind": "research_area_overview",
  "study_area": {
    "name": "Sanjiangyuan",
    "boundary_source": "current_map_aoi",
    "aoi_mode": "polygon",
    "bbox": [0, 0, 1, 1],
    "geometry": null
  },
  "basemap": {
    "type": "remote_sensing",
    "provider": "mpc",
    "collection": "landsat-c2-l2",
    "datetime": "2025-07-01/2025-07-31",
    "cloud_cover_lte": 20,
    "bands": ["red", "green", "blue"],
    "target_resolution": 120,
    "target_crs": "EPSG:3857"
  },
  "layout": {
    "title": "Research Area Overview Map",
    "template_id": "default",
    "layout_name": "Layout",
    "fit_padding": 0.08
  },
  "output": {
    "format": "jpg",
    "dpi": 300
  }
}
```

## Tool Contract

The first workflow uses these tools:

- `validate_map_spec`
- `search_remote_sensing_images`
- `select_best_image`
- `prepare_remote_sensing_basemap`
- `write_study_area_boundary`
- `render_research_area_overview_map`
- `check_map_output`

Tools wrap the existing REST services. The model talks to agent tools; the tools call
`data-service` and `carto-engine`.

## Formal Boundary Rule

The agent must not silently guess a named study-area boundary. If the current page context does not
provide a valid AOI, the agent asks the user to draw or provide one first.

## Data Preparation Failure Policy

If `data-service` cannot open signed remote COG assets, the agent records the completed search and
selected image in the task outputs, marks the prepare step as failed, and reports the failure as an
environment or cache-policy issue. It must not pretend that a final map was made.

The formal remediation paths are:

- Fix the `data-service` GDAL/rasterio runtime so it supports remote HTTPS COG range reads.
- Add an explicit asset cache/download policy for selected COG assets before raster preparation.
- Add a lower-fidelity preview fallback only if the output is clearly labeled as a preview map, not
  a final research-area map.

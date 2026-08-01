# Remote Sensing Basemap Skill

Use this skill after the user or agent has selected one remote-sensing image item.

Responsibilities:

- Build a raster preparation request for data-service.
- Preserve the selected `item_id`.
- Apply the configured band combination, target resolution, target CRS, and AOI.
- Produce a local render-ready GeoTIFF through the data-service prepare job.
- Update the expert agent context with `prepared_dataset_path`.
- Ensure downstream ArcPy map code loads the prepared dataset before export.

Current default basemap policy:

- Bands: `red`, `green`, `blue`.
- Target CRS: `EPSG:3857`.
- Target resolution: `30`.
- Output: GeoTIFF for cartographic rendering.

This skill does not render the final map. It prepares the raster that carto-engine will load.


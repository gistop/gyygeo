# Data Acquisition Skill

Use this skill when the expert cartography agent needs remote-sensing source data.

Responsibilities:

- Build a provider search request from the current AOI and user constraints.
- Call the data-service search endpoint through the agent tool layer.
- Preserve all candidate image items in task outputs.
- Recommend one candidate using the configured policy, but do not silently use it when human
  selection is required.
- Pause the expert workflow with `pending_action.type = "select_image"` so the user can choose a
  candidate image from the left-side search results.

Current recommendation policy:

- Prefer lower `cloud_cover`.
- If cloud cover ties, prefer the earlier `datetime`.
- Treat missing cloud cover as low confidence and rank it after numeric cloud-cover values.

This skill does not download data and does not prepare rasters. It hands the selected item to the
remote-sensing basemap skill.


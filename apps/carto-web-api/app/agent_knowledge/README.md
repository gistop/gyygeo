# Agent Knowledge Pack

This directory contains runtime knowledge for the gyygeo map-making agent.

The files here are not general documentation. They are curated, verified facts and examples that
`carto-web-api` can inject into expert-mode prompts before asking an LLM to generate ArcPy code.

Current priority:

- Prefer small, verified ArcPy patterns over broad API summaries.
- Record project-specific template facts such as layout names and element names.
- Include examples that have been executed successfully in this workspace.
- Keep generated ArcPy code compatible with the variables injected by `carto-engine`:
  `APRX_PATH`, `OUTPUT_DIR`, `OUTPUT_PATH`, `DPI`, and `CONTEXT`.

Suggested loading order for expert-mode code generation:

1. `arcpy_runtime.md`
2. Topic-specific files such as `arcpy_layout_text.md`, `arcpy_layout_elements.md`, or `arcpy_export.md`
3. Template facts from `templates/default.md`
4. One or two relevant examples from `examples/`

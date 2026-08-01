# Cartographic Standards Skill

Use this skill when the expert agent needs to turn cartographic presentation requirements
into structured operations.

Responsibilities:

- Interpret explicit typography requirements from the user request.
- Prefer structured `run_arcpy_code.text_styles` operations over handwritten ArcPy style code.
- Keep real ArcPy execution in carto-engine.
- Use stable layout element names such as `Title` for template text elements.

Current scope:

- Title typography: font family, font size, and font style.

This skill does not render or edit APRX files directly. It only prepares validated
cartographic operation parameters for engine tools.

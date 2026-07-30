# Template: default.aprx

Template path:

```text
apps/carto-engine/templates/aprx/default.aprx
```

Verified facts:

- The template has one layout.
- The layout name is `Layout`.
- There are currently no `TEXT_ELEMENT` elements in the layout.
- There is one `MAPFRAME_ELEMENT`.
- There are `MAPSURROUND_ELEMENT` elements, including:
  - `zbz`: north arrow

Implications for generated code:

- Do not assume a title text element exists.
- To add a title, create one with `aprx.createTextElement(...)`.
- To move the north arrow, use `layout.listElements("MAPSURROUND_ELEMENT", "zbz")`.
- Use `layout = aprx.listLayouts()[0]` when no specific layout name is requested.

import arcpy

aprx = arcpy.mp.ArcGISProject(APRX_PATH)
layout = aprx.listLayouts()[0]

matches = layout.listElements("MAPSURROUND_ELEMENT", "zbz")
if not matches:
    raise RuntimeError("North arrow element not found: zbz")

north_arrow = matches[0]
north_arrow.setAnchor("BOTTOM_LEFT_CORNER")
north_arrow.elementPositionX = 0.3
north_arrow.elementPositionY = 0.3

aprx.save()
layout.exportToJPEG(OUTPUT_PATH, resolution=DPI)
del aprx

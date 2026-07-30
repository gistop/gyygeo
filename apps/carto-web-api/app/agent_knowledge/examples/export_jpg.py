import arcpy

aprx = arcpy.mp.ArcGISProject(APRX_PATH)
layout = aprx.listLayouts()[0]

aprx.save()
layout.exportToJPEG(OUTPUT_PATH, resolution=DPI)
del aprx

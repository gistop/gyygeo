import arcpy

aprx = arcpy.mp.ArcGISProject(APRX_PATH)
layout = aprx.listLayouts()[0]

page_width = float(layout.pageWidth)
page_height = float(layout.pageHeight)
point = arcpy.Point(page_width / 2, page_height - 0.35)

title = aprx.createTextElement(
    layout,
    point,
    "POINT",
    "专家模式测试地图",
    text_size=24,
    font_family_name="Microsoft YaHei UI",
    font_style_name="Bold",
    name="Title",
)
title.setAnchor("CENTER_POINT")
title.elementPositionX = page_width / 2
title.elementPositionY = page_height - 0.35

aprx.save()
layout.exportToJPEG(OUTPUT_PATH, resolution=DPI)
del aprx

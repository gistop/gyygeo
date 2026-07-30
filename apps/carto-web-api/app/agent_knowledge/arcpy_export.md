# ArcPy Export

Generated expert-mode code must create `OUTPUT_PATH`.

For JPEG:

```python
layout.exportToJPEG(OUTPUT_PATH, resolution=DPI)
```

For PNG:

```python
layout.exportToPNG(OUTPUT_PATH, resolution=DPI)
```

For PDF:

```python
layout.exportToPDF(OUTPUT_PATH, resolution=DPI)
```

Recommended ending:

```python
aprx.save()
layout.exportToJPEG(OUTPUT_PATH, resolution=DPI)
del aprx
```

Do not export to a hard-coded path. Always use `OUTPUT_PATH`.

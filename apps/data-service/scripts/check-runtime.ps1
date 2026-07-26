. "$PSScriptRoot\_common.ps1"

$PythonExe = Get-GyyGeoDataPython
Assert-ProjectPython -PythonExe $PythonExe

& $PythonExe --version
& $PythonExe -c "import sys; print(sys.executable)"
& $PythonExe -c "import fastapi, pydantic, uvicorn; print('FastAPI', fastapi.__version__); print('Pydantic', pydantic.__version__); print('Uvicorn', uvicorn.__version__)"
& $PythonExe -c "import importlib.util; deps=['pystac_client','planetary_computer','rasterio','numpy']; missing=[d for d in deps if importlib.util.find_spec(d) is None]; print('MPC dependencies', 'ok' if not missing else 'missing: ' + ', '.join(missing))"


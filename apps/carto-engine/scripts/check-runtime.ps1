. "$PSScriptRoot\_common.ps1"

$PythonExe = Get-GyyGeoCartoPython
Assert-ProjectPython -PythonExe $PythonExe

function Invoke-CheckedPython {
    param(
        [Parameter(Mandatory = $true)]
        [string[]]$Arguments,
        [Parameter(Mandatory = $true)]
        [string]$FailureMessage
    )

    & $PythonExe @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "$FailureMessage Exit code: $LASTEXITCODE"
    }
}

& $PythonExe --version
Invoke-CheckedPython `
    -Arguments @(
        "-u",
        "-X",
        "faulthandler",
        "-c",
        "import arcpy; print('ArcPy', arcpy.GetInstallInfo().get('Version')); print('License', arcpy.ProductInfo())"
    ) `
    -FailureMessage "ArcPy runtime check failed."

Invoke-CheckedPython `
    -Arguments @(
        "-c",
        "import fastapi, pydantic, uvicorn; print('FastAPI', fastapi.__version__); print('Pydantic', pydantic.__version__); print('Uvicorn', uvicorn.__version__)"
    ) `
    -FailureMessage "FastAPI runtime check failed."

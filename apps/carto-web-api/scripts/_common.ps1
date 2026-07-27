$ErrorActionPreference = "Stop"

$Script:ProjectRoot = Split-Path -Parent $PSScriptRoot
$Script:ArcGisBaseEnv = "C:\Program Files\ArcGIS\Pro\bin\Python\envs\arcgispro-py3"
$Script:ArcGisBasePython = Join-Path $Script:ArcGisBaseEnv "python.exe"
$Script:ArcGisConda = "C:\Program Files\ArcGIS\Pro\bin\Python\Scripts\conda.exe"
$Script:ProjectEnvName = "gyygeo-web-api-py3"
$Script:ProjectEnvDir = Join-Path $env:LOCALAPPDATA "ESRI\conda\envs\$Script:ProjectEnvName"
$Script:DefaultProjectPython = Join-Path $Script:ProjectEnvDir "python.exe"

function Get-GyyGeoWebApiPython {
    if ($env:GYYGEO_WEB_API_PYTHON_EXE) {
        return [Environment]::ExpandEnvironmentVariables($env:GYYGEO_WEB_API_PYTHON_EXE)
    }

    return $Script:DefaultProjectPython
}

function Assert-PathExists {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path,
        [Parameter(Mandatory = $true)]
        [string]$Message
    )

    if (-not (Test-Path -LiteralPath $Path)) {
        throw $Message
    }
}

function Assert-ProjectPython {
    param(
        [Parameter(Mandatory = $true)]
        [string]$PythonExe
    )

    Assert-PathExists `
        -Path $PythonExe `
        -Message "gyygeo web API Python was not found: $PythonExe. Run scripts\create-env.ps1 first."

    Assert-PathExists `
        -Path $Script:ArcGisBasePython `
        -Message "ArcGIS Pro base Python was not found: $Script:ArcGisBasePython"

    $resolvedProject = (Resolve-Path -LiteralPath $PythonExe).Path
    $resolvedBase = (Resolve-Path -LiteralPath $Script:ArcGisBasePython).Path

    if ($resolvedProject -eq $resolvedBase) {
        throw "Refusing to use the original ArcGIS Pro Python environment. Use the gyygeo-web-api-py3 environment instead."
    }
}

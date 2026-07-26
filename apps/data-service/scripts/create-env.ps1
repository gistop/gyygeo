. "$PSScriptRoot\_common.ps1"

Assert-PathExists `
    -Path $Script:ArcGisConda `
    -Message "ArcGIS Pro conda was not found: $Script:ArcGisConda"

if (Test-Path -LiteralPath $Script:DefaultProjectPython) {
    Write-Output "Project environment already exists: $Script:ProjectEnvDir"
    & $Script:DefaultProjectPython --version
    exit 0
}

if (Test-Path -LiteralPath $Script:ProjectEnvDir) {
    throw "Incomplete project environment found: $Script:ProjectEnvDir. Run scripts\reset-env.ps1, then run scripts\create-env.ps1 again."
}

New-Item -ItemType Directory -Force -Path (Split-Path -Parent $Script:ProjectEnvDir) | Out-Null

& $Script:ArcGisConda create `
    --yes `
    --prefix $Script:ProjectEnvDir `
    python=3.13 `
    pip

if ($LASTEXITCODE -ne 0) {
    throw "Failed to create data-service Python environment at $Script:ProjectEnvDir. Conda exit code: $LASTEXITCODE"
}

Assert-PathExists `
    -Path $Script:DefaultProjectPython `
    -Message "Environment creation completed without a usable python.exe: $Script:DefaultProjectPython"

& $Script:DefaultProjectPython --version

. "$PSScriptRoot\_common.ps1"

Assert-PathExists `
    -Path $Script:ArcGisConda `
    -Message "ArcGIS Pro conda was not found: $Script:ArcGisConda"

Assert-PathExists `
    -Path $Script:ArcGisBasePython `
    -Message "ArcGIS Pro base Python was not found: $Script:ArcGisBasePython"

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
    --clone $Script:ArcGisBaseEnv

if ($LASTEXITCODE -ne 0) {
    throw "Failed to clone ArcGIS Pro Python into $Script:ProjectEnvDir. Conda exit code: $LASTEXITCODE"
}

Assert-PathExists `
    -Path $Script:DefaultProjectPython `
    -Message "Environment clone completed without a usable python.exe: $Script:DefaultProjectPython"

& $Script:DefaultProjectPython --version

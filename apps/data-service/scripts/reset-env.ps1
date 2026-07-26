. "$PSScriptRoot\_common.ps1"

$expectedSuffix = "ESRI\conda\envs\$Script:ProjectEnvName"
$resolvedParent = Resolve-Path -LiteralPath (Split-Path -Parent $Script:ProjectEnvDir)
$absoluteEnvDir = Join-Path $resolvedParent.Path $Script:ProjectEnvName

if (-not $absoluteEnvDir.EndsWith($expectedSuffix, [StringComparison]::OrdinalIgnoreCase)) {
    throw "Refusing to remove unexpected environment path: $absoluteEnvDir"
}

if (-not (Test-Path -LiteralPath $absoluteEnvDir)) {
    Write-Output "Project environment does not exist: $absoluteEnvDir"
    exit 0
}

Write-Output "Removing project environment: $absoluteEnvDir"

if (Test-Path -LiteralPath $absoluteEnvDir) {
    Remove-Item -LiteralPath $absoluteEnvDir -Recurse -Force
}

Write-Output "Removed project environment: $absoluteEnvDir"


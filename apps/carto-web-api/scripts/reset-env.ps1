. "$PSScriptRoot\_common.ps1"

if (-not (Test-Path -LiteralPath $Script:ProjectEnvDir)) {
    Write-Output "Project environment does not exist: $Script:ProjectEnvDir"
    exit 0
}

$resolvedEnv = (Resolve-Path -LiteralPath $Script:ProjectEnvDir).Path
$resolvedParent = (Resolve-Path -LiteralPath (Split-Path -Parent $Script:ProjectEnvDir)).Path

if (-not $resolvedEnv.StartsWith($resolvedParent, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "Refusing to remove unexpected environment path: $resolvedEnv"
}

Remove-Item -LiteralPath $resolvedEnv -Recurse -Force
Write-Output "Removed project environment: $resolvedEnv"

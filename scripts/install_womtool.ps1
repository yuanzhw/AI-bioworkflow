param(
    [string]$Version = "91",
    [string]$InstallDir = ".cache/womtool"
)

$ErrorActionPreference = "Stop"

$root = Resolve-Path "."
$targetDir = Join-Path $root $InstallDir
$versionedJar = Join-Path $targetDir "womtool-$Version.jar"
$defaultJar = Join-Path $targetDir "womtool.jar"
$url = "https://github.com/broadinstitute/cromwell/releases/download/$Version/womtool-$Version.jar"

New-Item -ItemType Directory -Force -Path $targetDir | Out-Null

Write-Host "Downloading WOMtool $Version..."
Invoke-WebRequest -Uri $url -OutFile $versionedJar
Copy-Item -LiteralPath $versionedJar -Destination $defaultJar -Force

Write-Host "WOMTOOL_JAR=$defaultJar"
Write-Host "Downloaded $versionedJar"

param(
    [string]$Version = "92",
    [string]$InstallDir = ".cache/womtool",
    [string]$Sha256 = ""
)

$ErrorActionPreference = "Stop"

$root = Resolve-Path "."
$targetDir = Join-Path $root $InstallDir
$versionedJar = Join-Path $targetDir "womtool-$Version.jar"
$downloadJar = Join-Path $targetDir ".womtool-$Version.jar.download"
$defaultJar = Join-Path $targetDir "womtool.jar"
$url = "https://github.com/broadinstitute/cromwell/releases/download/$Version/womtool-$Version.jar"
$knownSha256 = @{
    "92" = "99cd3675c48696470f4d4e8b397fc613d7b342eb2ef2fa96f86db114bd9ed5f8"
}

$expectedSha256 = $Sha256.Trim().ToLowerInvariant()
if (-not $expectedSha256) {
    $expectedSha256 = $knownSha256[$Version]
}
if (-not $expectedSha256) {
    throw "No trusted SHA-256 is recorded for WOMtool $Version. Pass -Sha256 explicitly."
}
if ($expectedSha256 -notmatch "^[0-9a-f]{64}$") {
    throw "Sha256 must be exactly 64 hexadecimal characters."
}

New-Item -ItemType Directory -Force -Path $targetDir | Out-Null

Write-Host "Downloading WOMtool $Version..."
try {
    Invoke-WebRequest -Uri $url -OutFile $downloadJar
    $actualSha256 = (Get-FileHash -LiteralPath $downloadJar -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($actualSha256 -ne $expectedSha256) {
        throw "WOMtool $Version SHA-256 mismatch. Expected $expectedSha256, got $actualSha256."
    }
    Move-Item -LiteralPath $downloadJar -Destination $versionedJar -Force
}
finally {
    if (Test-Path -LiteralPath $downloadJar) {
        Remove-Item -LiteralPath $downloadJar -Force
    }
}
Copy-Item -LiteralPath $versionedJar -Destination $defaultJar -Force

Write-Host "WOMTOOL_JAR=$defaultJar"
Write-Host "Downloaded $versionedJar"
Write-Host "SHA256=$actualSha256"

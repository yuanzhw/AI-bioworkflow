param(
    [string]$MajorVersion = "17",
    [string]$InstallDir = ".cache/java/temurin-17"
)

$ErrorActionPreference = "Stop"

$root = Resolve-Path "."
$targetRoot = Join-Path $root $InstallDir
$archive = Join-Path $targetRoot "temurin-$MajorVersion-jdk.zip"
$url = "https://api.adoptium.net/v3/binary/latest/$MajorVersion/ga/windows/x64/jdk/hotspot/normal/eclipse?project=jdk"

New-Item -ItemType Directory -Force -Path $targetRoot | Out-Null

Write-Host "Downloading Temurin JDK $MajorVersion..."
Invoke-WebRequest -Uri $url -OutFile $archive

$extractDir = Join-Path $targetRoot "extract"
if (Test-Path $extractDir) {
    Remove-Item -LiteralPath $extractDir -Recurse -Force
}
New-Item -ItemType Directory -Force -Path $extractDir | Out-Null

Write-Host "Extracting Temurin JDK $MajorVersion..."
Expand-Archive -LiteralPath $archive -DestinationPath $extractDir -Force

$java = Get-ChildItem -Path $extractDir -Recurse -Filter "java.exe" | Select-Object -First 1
if (-not $java) {
    throw "java.exe was not found after extraction."
}

$jdkHome = Split-Path -Parent (Split-Path -Parent $java.FullName)
Write-Host "JAVA_HOME=$jdkHome"
Write-Host "JAVA_EXE=$($java.FullName)"
& $java.FullName -version

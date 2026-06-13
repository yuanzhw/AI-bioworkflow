param(
    [string]$WindowsFixtureRoot = "C:\data\ai-bioworkflow-tiny",
    [string]$CromwellFixtureRoot = "/data/ai-bioworkflow-runner/tiny",
    [string]$CromwellUrl = "http://localhost:8000",
    [ValidateSet("auto", "docker", "podman")]
    [string]$ContainerRuntime = "auto",
    [ValidateSet("docker", "wsl")]
    [string]$SyncMode = "docker",
    [string]$CromwellContainerName = "cromwell-cromwell-1",
    [string]$PythonExe = "",
    [string]$WslDistro = "",
    [switch]$SkipPrepare,
    [switch]$SkipWslSync,
    [switch]$NoTest
)

$ErrorActionPreference = "Stop"

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
if (-not $PythonExe) {
    $PythonExe = Join-Path $repoRoot ".venv\Scripts\python.exe"
}

if (-not (Test-Path -LiteralPath $PythonExe)) {
    throw "Python executable not found: $PythonExe"
}

function Invoke-WslCommand {
    param(
        [Parameter(Mandatory = $true)][string]$Command,
        [string[]]$CommandArguments = @()
    )

    if (-not (Get-Command wsl.exe -ErrorAction SilentlyContinue)) {
        throw "wsl.exe is required unless -SkipWslSync is set."
    }

    $arguments = @()
    if ($WslDistro) {
        $arguments += @("-d", $WslDistro)
    }
    $arguments += @("--", $Command)
    $arguments += $CommandArguments

    & wsl.exe @arguments
    if ($LASTEXITCODE -ne 0) {
        throw "WSL command failed with exit code $LASTEXITCODE"
    }
}

function Invoke-DockerCommand {
    param([Parameter(Mandatory = $true)][string[]]$Arguments)

    if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
        throw "docker is required for -SyncMode docker."
    }

    & docker @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "docker command failed with exit code $LASTEXITCODE"
    }
}

function ConvertTo-WslPath {
    param([Parameter(Mandatory = $true)][string]$WindowsPath)

    $pathForWslpath = $WindowsPath.Replace("\", "/")
    $arguments = @()
    if ($WslDistro) {
        $arguments += @("-d", $WslDistro)
    }
    $arguments += @("--", "wslpath", "-a", $pathForWslpath)

    $result = & wsl.exe @arguments
    if ($LASTEXITCODE -ne 0) {
        throw "wslpath failed with exit code $LASTEXITCODE"
    }

    $wslPath = $result | Where-Object { $_ -like "/*" } | Select-Object -First 1
    if (-not $wslPath) {
        throw "wslpath did not return a WSL path for: $WindowsPath"
    }
    return $wslPath.Trim()
}

function Sync-FixtureWithDocker {
    param(
        [Parameter(Mandatory = $true)][string]$FixtureRoot,
        [Parameter(Mandatory = $true)][string]$TargetRoot
    )

    Write-Host "Syncing tiny fixture into Cromwell container: $FixtureRoot -> $CromwellContainerName`:$TargetRoot"
    Invoke-DockerCommand @("exec", $CromwellContainerName, "mkdir", "-p", $TargetRoot)

    $source = Join-Path $FixtureRoot "."
    $target = "${CromwellContainerName}:$TargetRoot"
    Invoke-DockerCommand @("cp", $source, $target)

    Invoke-DockerCommand @("exec", $CromwellContainerName, "test", "-f", "$TargetRoot/rnaseq_deg.inputs.json")
    Invoke-DockerCommand @("exec", $CromwellContainerName, "test", "-f", "$TargetRoot/salmon_index/versionInfo.json")
}

function Sync-FixtureWithWsl {
    param(
        [Parameter(Mandatory = $true)][string]$FixtureRoot,
        [Parameter(Mandatory = $true)][string]$TargetRoot
    )

    $wslSource = ConvertTo-WslPath $FixtureRoot
    Write-Host "Syncing tiny fixture into WSL: $wslSource -> $TargetRoot"
    Invoke-WslCommand "mkdir" @("-p", $TargetRoot)
    Invoke-WslCommand "cp" @("-a", "$wslSource/.", "$TargetRoot/")
    Invoke-WslCommand "test" @("-f", "$TargetRoot/rnaseq_deg.inputs.json")
    Invoke-WslCommand "test" @("-f", "$TargetRoot/salmon_index/versionInfo.json")
}

Push-Location $repoRoot
try {
    $fixtureRoot = [System.IO.Path]::GetFullPath($WindowsFixtureRoot)
    $inputsPath = Join-Path $fixtureRoot "rnaseq_deg.inputs.json"

    if (-not $SkipPrepare) {
        & $PythonExe `
            "examples\tiny\prepare_tiny_data.py" `
            --fixture-root $fixtureRoot `
            --write-inputs $inputsPath `
            --cromwell-root $CromwellFixtureRoot `
            --container-runtime $ContainerRuntime
        if ($LASTEXITCODE -ne 0) {
            throw "prepare_tiny_data.py failed with exit code $LASTEXITCODE"
        }
    }

    if (-not $SkipWslSync) {
        if ($SyncMode -eq "docker") {
            Sync-FixtureWithDocker $fixtureRoot $CromwellFixtureRoot
        }
        else {
            Sync-FixtureWithWsl $fixtureRoot $CromwellFixtureRoot
        }
    }

    if ($NoTest) {
        Write-Host "Prepared tiny fixture inputs at $inputsPath"
        Write-Host "Cromwell-visible fixture root: $CromwellFixtureRoot"
        return
    }

    $previousEnv = @{
        AI_BIOWORKFLOW_RUN_E2E = $env:AI_BIOWORKFLOW_RUN_E2E
        AI_BIOWORKFLOW_RUN_BACKEND = $env:AI_BIOWORKFLOW_RUN_BACKEND
        CROMWELL_URL = $env:CROMWELL_URL
        AI_BIOWORKFLOW_TINY_INPUTS = $env:AI_BIOWORKFLOW_TINY_INPUTS
    }

    try {
        $env:AI_BIOWORKFLOW_RUN_E2E = "1"
        $env:AI_BIOWORKFLOW_RUN_BACKEND = "cromwell"
        $env:CROMWELL_URL = $CromwellUrl
        $env:AI_BIOWORKFLOW_TINY_INPUTS = $inputsPath

        & $PythonExe -m unittest tests.e2e.test_tiny_run -v
        if ($LASTEXITCODE -ne 0) {
            exit $LASTEXITCODE
        }
    }
    finally {
        foreach ($name in $previousEnv.Keys) {
            if ($null -eq $previousEnv[$name]) {
                Remove-Item "Env:\$name" -ErrorAction SilentlyContinue
            }
            else {
                Set-Item "Env:\$name" $previousEnv[$name]
            }
        }
    }
}
finally {
    Pop-Location
}

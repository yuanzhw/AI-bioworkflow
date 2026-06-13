param(
    [string]$PythonExe = "",
    [string]$OutputDir = ".cache\p0",
    [switch]$SkipUnitTests,
    [switch]$SkipCompile,
    [switch]$RunE2E,
    [string]$WindowsFixtureRoot = "C:\data\ai-bioworkflow-tiny",
    [string]$CromwellFixtureRoot = "/data/ai-bioworkflow-runner/tiny",
    [string]$CromwellUrl = "http://localhost:8000",
    [string]$ContainerRuntime = "docker",
    [ValidateSet("docker", "wsl")]
    [string]$SyncMode = "docker",
    [string]$CromwellContainerName = "cromwell-cromwell-1",
    [string]$WslDistro = "",
    [switch]$SkipPrepare,
    [switch]$SkipWslSync
)

$ErrorActionPreference = "Stop"

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$locationPushed = $false
$pythonCommand = @()
$pythonExeForScripts = ""

function Set-PythonCommand {
    if ($PythonExe) {
        if (-not (Test-Path -LiteralPath $PythonExe)) {
            throw "Python executable not found: $PythonExe"
        }
        $script:pythonCommand = @($PythonExe)
        $script:pythonExeForScripts = $PythonExe
        return
    }

    $venvPython = Join-Path $repoRoot ".venv\Scripts\python.exe"
    if (Test-Path -LiteralPath $venvPython) {
        $script:pythonCommand = @($venvPython)
        $script:pythonExeForScripts = $venvPython
        return
    }

    if (Get-Command uv -ErrorAction SilentlyContinue) {
        $script:pythonCommand = @("uv", "run", "python")
        $script:pythonExeForScripts = ""
        return
    }

    throw "No Python runtime found. Expected .venv\Scripts\python.exe or uv on PATH."
}

function Invoke-Python {
    param([Parameter(Mandatory = $true)][string[]]$Arguments)

    $command = $script:pythonCommand[0]
    $commandArgs = @()
    if ($script:pythonCommand.Count -gt 1) {
        $commandArgs += $script:pythonCommand[1..($script:pythonCommand.Count - 1)]
    }
    $commandArgs += $Arguments

    & $command @commandArgs
    if ($LASTEXITCODE -ne 0) {
        throw "Python command failed with exit code ${LASTEXITCODE}: $($Arguments -join ' ')"
    }
}

function Invoke-Step {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][scriptblock]$Action
    )

    Write-Host ""
    Write-Host "==> $Name"
    $timer = [System.Diagnostics.Stopwatch]::StartNew()
    & $Action
    $timer.Stop()
    Write-Host "OK: $Name ($([Math]::Round($timer.Elapsed.TotalSeconds, 1))s)"
}

function Resolve-OutputDirectory {
    if ([System.IO.Path]::IsPathRooted($OutputDir)) {
        return [System.IO.Path]::GetFullPath($OutputDir)
    }
    return [System.IO.Path]::GetFullPath((Join-Path $repoRoot $OutputDir))
}

try {
    Set-PythonCommand
    Push-Location $repoRoot
    $locationPushed = $true

    Write-Host "P0 check root: $repoRoot"
    Write-Host "Python: $($pythonCommand -join ' ')"

    if (-not $SkipUnitTests) {
        Invoke-Step "Unit and compiler tests" {
            Invoke-Python @("-m", "unittest", "discover", "-v")
        }
    }

    if (-not $SkipCompile) {
        Invoke-Step "Representative RNA-seq WDL compile and WOMtool validation" {
            $resolvedOutputDir = Resolve-OutputDirectory
            New-Item -ItemType Directory -Force -Path $resolvedOutputDir | Out-Null
            $wdlPath = Join-Path $resolvedOutputDir "rnaseq_deg.wdl"
            Invoke-Python @(
                "main.py",
                "--input", "examples\rnaseq_deg_recipe_plan.json",
                "--output", $wdlPath
            )
            if (-not (Test-Path -LiteralPath $wdlPath)) {
                throw "Expected WDL output was not created: $wdlPath"
            }
            Write-Host "WDL: $wdlPath"
        }
    }

    if ($RunE2E) {
        Invoke-Step "Cromwell tiny RNA-seq e2e" {
            $e2eScript = Join-Path $PSScriptRoot "run_cromwell_tiny_e2e.ps1"
            if (-not (Test-Path -LiteralPath $e2eScript)) {
                throw "Cromwell tiny e2e helper not found: $e2eScript"
            }
            if (-not $pythonExeForScripts) {
                throw "Cromwell tiny e2e requires a concrete Python executable. Create .venv\Scripts\python.exe or pass -PythonExe <path>; the uv fallback only supports local unit/compile checks."
            }

            $e2eArgs = @(
                "-ExecutionPolicy", "Bypass",
                "-File", $e2eScript,
                "-WindowsFixtureRoot", $WindowsFixtureRoot,
                "-CromwellFixtureRoot", $CromwellFixtureRoot,
                "-CromwellUrl", $CromwellUrl,
                "-ContainerRuntime", $ContainerRuntime,
                "-SyncMode", $SyncMode,
                "-CromwellContainerName", $CromwellContainerName
            )
            if ($pythonExeForScripts) {
                $e2eArgs += @("-PythonExe", $pythonExeForScripts)
            }
            if ($WslDistro) {
                $e2eArgs += @("-WslDistro", $WslDistro)
            }
            if ($SkipPrepare) {
                $e2eArgs += "-SkipPrepare"
            }
            if ($SkipWslSync) {
                $e2eArgs += "-SkipWslSync"
            }

            & powershell @e2eArgs
            if ($LASTEXITCODE -ne 0) {
                throw "Cromwell tiny e2e helper failed with exit code $LASTEXITCODE"
            }
        }
    }
    else {
        Write-Host ""
        Write-Host "Skipping real Cromwell e2e. Re-run with -RunE2E to opt in."
    }

    Write-Host ""
    Write-Host "P0 check passed."
}
catch {
    Write-Error $_
    exit 1
}
finally {
    if ($locationPushed) {
        Pop-Location
    }
}

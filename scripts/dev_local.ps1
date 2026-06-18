param(
    [string]$PythonExe = "",
    [string]$ApiHost = "127.0.0.1",
    [ValidateRange(1, 65535)]
    [int]$ApiPort = 8010,
    [string]$WebHost = "127.0.0.1",
    [ValidateRange(1, 65535)]
    [int]$WebPort = 3000,
    [string]$ApiBaseUrl = "",
    [switch]$ApiOnly,
    [switch]$WebOnly,
    [switch]$DryRun,
    [switch]$SkipPortCheck
)

$ErrorActionPreference = "Stop"

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$webRoot = Join-Path $repoRoot "web"
$script:pythonCommand = @()

function Set-PythonCommand {
    if ($PythonExe) {
        if (-not (Test-Path -LiteralPath $PythonExe)) {
            throw "Python executable not found: $PythonExe"
        }
        $script:pythonCommand = @($PythonExe)
        return
    }

    $venvPython = Join-Path $repoRoot ".venv\Scripts\python.exe"
    if (Test-Path -LiteralPath $venvPython) {
        $script:pythonCommand = @($venvPython)
        return
    }

    if (Get-Command uv -ErrorAction SilentlyContinue) {
        $script:pythonCommand = @("uv", "run", "python")
        return
    }

    throw "No Python runtime found. Expected .venv\Scripts\python.exe or uv on PATH."
}

function Resolve-ApiBaseUrl {
    if ($ApiBaseUrl) {
        return $ApiBaseUrl.TrimEnd("/")
    }
    return "http://${ApiHost}:${ApiPort}"
}

function Get-WebCorsOrigins {
    $origins = @("http://${WebHost}:${WebPort}")
    if ($WebHost -eq "127.0.0.1") {
        $origins += "http://localhost:${WebPort}"
    }
    elseif ($WebHost -eq "localhost") {
        $origins += "http://127.0.0.1:${WebPort}"
    }

    return (($origins | Select-Object -Unique) -join ",")
}

function Test-TcpPortAvailable {
    param(
        [Parameter(Mandatory = $true)][string]$HostName,
        [Parameter(Mandatory = $true)][int]$Port
    )

    $listener = $null
    try {
        $address = [System.Net.IPAddress]::Any
        if (-not [System.Net.IPAddress]::TryParse($HostName, [ref]$address)) {
            $address = [System.Net.Dns]::GetHostAddresses($HostName) |
                Where-Object { $_.AddressFamily -eq [System.Net.Sockets.AddressFamily]::InterNetwork } |
                Select-Object -First 1
        }

        if ($null -eq $address) {
            return $false
        }

        $listener = [System.Net.Sockets.TcpListener]::new($address, $Port)
        $listener.Start()
        return $true
    }
    catch {
        return $false
    }
    finally {
        if ($null -ne $listener) {
            $listener.Stop()
        }
    }
}

function Assert-PortAvailable {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][string]$HostName,
        [Parameter(Mandatory = $true)][int]$Port
    )

    if ($SkipPortCheck) {
        return
    }

    if (-not (Test-TcpPortAvailable -HostName $HostName -Port $Port)) {
        throw "$Name port is already in use: ${HostName}:${Port}. Pass a different port or use -SkipPortCheck if this is expected."
    }
}

function Assert-WebReady {
    if (-not (Test-Path -LiteralPath (Join-Path $webRoot "package.json"))) {
        throw "Web package.json not found: $webRoot"
    }
    if (-not (Get-Command npm -ErrorAction SilentlyContinue)) {
        throw "npm was not found on PATH. Install Node.js/npm before starting the web app."
    }
    if (-not (Test-Path -LiteralPath (Join-Path $webRoot "node_modules"))) {
        throw "Web dependencies are not installed. Run 'npm install' from the web directory first."
    }
}

function Invoke-ApiServer {
    param(
        [Parameter(Mandatory = $true)][string[]]$PythonCommand,
        [Parameter(Mandatory = $true)][string]$CorsOrigins
    )

    $env:AI_BIOWORKFLOW_API_HOST = $ApiHost
    $env:AI_BIOWORKFLOW_API_PORT = [string]$ApiPort
    $env:AI_BIOWORKFLOW_CORS_ORIGINS = $CorsOrigins

    Push-Location $repoRoot
    try {
        $command = $PythonCommand[0]
        $commandArgs = @()
        if ($PythonCommand.Count -gt 1) {
            $commandArgs += $PythonCommand[1..($PythonCommand.Count - 1)]
        }
        $commandArgs += @("-m", "src.api.server")

        & $command @commandArgs
        if ($LASTEXITCODE -ne 0) {
            throw "API server exited with code $LASTEXITCODE"
        }
    }
    finally {
        Pop-Location
    }
}

function Invoke-WebServer {
    param([Parameter(Mandatory = $true)][string]$ResolvedApiBaseUrl)

    $env:NEXT_PUBLIC_API_BASE_URL = $ResolvedApiBaseUrl

    Push-Location $webRoot
    try {
        & npm run dev -- -H $WebHost -p $WebPort
        if ($LASTEXITCODE -ne 0) {
            throw "Next.js dev server exited with code $LASTEXITCODE"
        }
    }
    finally {
        Pop-Location
    }
}

function Start-ApiJob {
    param(
        [Parameter(Mandatory = $true)][string[]]$PythonCommand,
        [Parameter(Mandatory = $true)][string]$CorsOrigins
    )

    Start-Job -Name "api" -ScriptBlock {
        param($RepoRoot, $PythonCommand, $ApiHost, $ApiPort, $CorsOrigins)

        $ErrorActionPreference = "Stop"
        Set-Location $RepoRoot
        $env:AI_BIOWORKFLOW_API_HOST = $ApiHost
        $env:AI_BIOWORKFLOW_API_PORT = [string]$ApiPort
        $env:AI_BIOWORKFLOW_CORS_ORIGINS = $CorsOrigins

        $command = $PythonCommand[0]
        $commandArgs = @()
        if ($PythonCommand.Count -gt 1) {
            $commandArgs += $PythonCommand[1..($PythonCommand.Count - 1)]
        }
        $commandArgs += @("-m", "src.api.server")

        & $command @commandArgs 2>&1 | ForEach-Object { "[api] $_" }
        if ($LASTEXITCODE -ne 0) {
            throw "API server exited with code $LASTEXITCODE"
        }
    } -ArgumentList $repoRoot, $PythonCommand, $ApiHost, $ApiPort, $CorsOrigins
}

function Start-WebJob {
    param([Parameter(Mandatory = $true)][string]$ResolvedApiBaseUrl)

    Start-Job -Name "web" -ScriptBlock {
        param($WebRoot, $WebHost, $WebPort, $ResolvedApiBaseUrl)

        $ErrorActionPreference = "Stop"
        Set-Location $WebRoot
        $env:NEXT_PUBLIC_API_BASE_URL = $ResolvedApiBaseUrl

        & npm run dev -- -H $WebHost -p $WebPort 2>&1 | ForEach-Object { "[web] $_" }
        if ($LASTEXITCODE -ne 0) {
            throw "Next.js dev server exited with code $LASTEXITCODE"
        }
    } -ArgumentList $webRoot, $WebHost, $WebPort, $ResolvedApiBaseUrl
}

function Receive-DevJobs {
    param([Parameter(Mandatory = $true)][object[]]$Jobs)

    while ($true) {
        foreach ($job in $Jobs) {
            Receive-Job -Job $job
        }

        $stoppedJobs = @($Jobs | Where-Object { $_.State -ne "Running" })
        if ($stoppedJobs.Count -gt 0) {
            foreach ($job in $stoppedJobs) {
                Receive-Job -Job $job
            }
            $names = ($stoppedJobs | ForEach-Object { "$($_.Name):$($_.State)" }) -join ", "
            throw "One or more dev services stopped: $names"
        }

        Start-Sleep -Seconds 1
    }
}

if ($ApiOnly -and $WebOnly) {
    throw "Choose at most one of -ApiOnly or -WebOnly."
}

Set-PythonCommand
$resolvedApiBaseUrl = Resolve-ApiBaseUrl
$corsOrigins = Get-WebCorsOrigins

if (-not $WebOnly) {
    Assert-PortAvailable -Name "API" -HostName $ApiHost -Port $ApiPort
}
if (-not $ApiOnly) {
    Assert-WebReady
    Assert-PortAvailable -Name "Web" -HostName $WebHost -Port $WebPort
}

Write-Host "AI-bioworkflow local dev"
Write-Host "Repo: $repoRoot"
if (-not $WebOnly) {
    Write-Host "API:  http://${ApiHost}:${ApiPort}"
    Write-Host "Docs: http://${ApiHost}:${ApiPort}/docs"
}
if (-not $ApiOnly) {
    Write-Host "Web:  http://${WebHost}:${WebPort}"
    Write-Host "NEXT_PUBLIC_API_BASE_URL=$resolvedApiBaseUrl"
}
Write-Host "Press Ctrl+C to stop."

if ($DryRun) {
    Write-Host "Dry run complete. No dev services were started."
    exit 0
}

if ($ApiOnly) {
    Invoke-ApiServer -PythonCommand $script:pythonCommand -CorsOrigins $corsOrigins
    exit 0
}

if ($WebOnly) {
    Invoke-WebServer -ResolvedApiBaseUrl $resolvedApiBaseUrl
    exit 0
}

$jobs = @()
try {
    $jobs += Start-ApiJob -PythonCommand $script:pythonCommand -CorsOrigins $corsOrigins
    $jobs += Start-WebJob -ResolvedApiBaseUrl $resolvedApiBaseUrl
    Receive-DevJobs -Jobs $jobs
}
finally {
    foreach ($job in $jobs) {
        Stop-Job -Job $job -ErrorAction SilentlyContinue
        Remove-Job -Job $job -Force -ErrorAction SilentlyContinue
    }
}

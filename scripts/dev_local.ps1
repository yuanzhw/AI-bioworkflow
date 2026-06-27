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
$script:devInvocationId = [Guid]::NewGuid().ToString("N")
$script:devProcessRoot = Join-Path ([System.IO.Path]::GetTempPath()) "ai-bioworkflow-dev-$PID-$script:devInvocationId"
$script:devJobObjectHandle = [IntPtr]::Zero

# Windows Job Objects provide kernel-level cleanup when this script exits before finally runs.
function Initialize-DevJobObjectSupport {
    if ("AIWorkflowDevJobObject" -as [type]) {
        return
    }

    Add-Type -TypeDefinition @'
using System;
using System.ComponentModel;
using System.Runtime.InteropServices;

public static class AIWorkflowDevJobObject
{
    private const int JobObjectExtendedLimitInformation = 9;
    private const uint JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000;
    private const uint PROCESS_TERMINATE = 0x0001;
    private const uint PROCESS_SET_QUOTA = 0x0100;

    [StructLayout(LayoutKind.Sequential)]
    private struct IO_COUNTERS
    {
        public ulong ReadOperationCount;
        public ulong WriteOperationCount;
        public ulong OtherOperationCount;
        public ulong ReadTransferCount;
        public ulong WriteTransferCount;
        public ulong OtherTransferCount;
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct JOBOBJECT_BASIC_LIMIT_INFORMATION
    {
        public long PerProcessUserTimeLimit;
        public long PerJobUserTimeLimit;
        public uint LimitFlags;
        public UIntPtr MinimumWorkingSetSize;
        public UIntPtr MaximumWorkingSetSize;
        public uint ActiveProcessLimit;
        public UIntPtr Affinity;
        public uint PriorityClass;
        public uint SchedulingClass;
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct JOBOBJECT_EXTENDED_LIMIT_INFORMATION
    {
        public JOBOBJECT_BASIC_LIMIT_INFORMATION BasicLimitInformation;
        public IO_COUNTERS IoInfo;
        public UIntPtr ProcessMemoryLimit;
        public UIntPtr JobMemoryLimit;
        public UIntPtr PeakProcessMemoryUsed;
        public UIntPtr PeakJobMemoryUsed;
    }

    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    private static extern IntPtr CreateJobObject(IntPtr lpJobAttributes, string lpName);

    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern bool SetInformationJobObject(
        IntPtr hJob,
        int jobObjectInfoClass,
        IntPtr lpJobObjectInfo,
        uint cbJobObjectInfoLength);

    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern bool AssignProcessToJobObject(IntPtr hJob, IntPtr hProcess);

    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern IntPtr OpenProcess(uint dwDesiredAccess, bool bInheritHandle, int dwProcessId);

    [DllImport("kernel32.dll", SetLastError = true)]
    public static extern bool CloseHandle(IntPtr hObject);

    public static IntPtr CreateKillOnCloseJob(string name)
    {
        IntPtr job = CreateJobObject(IntPtr.Zero, name);
        if (job == IntPtr.Zero)
        {
            throw new Win32Exception(Marshal.GetLastWin32Error());
        }

        JOBOBJECT_EXTENDED_LIMIT_INFORMATION info = new JOBOBJECT_EXTENDED_LIMIT_INFORMATION();
        info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE;

        int length = Marshal.SizeOf(typeof(JOBOBJECT_EXTENDED_LIMIT_INFORMATION));
        IntPtr infoPtr = Marshal.AllocHGlobal(length);
        try
        {
            Marshal.StructureToPtr(info, infoPtr, false);
            if (!SetInformationJobObject(job, JobObjectExtendedLimitInformation, infoPtr, (uint)length))
            {
                int error = Marshal.GetLastWin32Error();
                CloseHandle(job);
                throw new Win32Exception(error);
            }
        }
        finally
        {
            Marshal.FreeHGlobal(infoPtr);
        }

        return job;
    }

    public static int TryAssignProcessId(IntPtr job, int processId)
    {
        IntPtr process = OpenProcess(PROCESS_TERMINATE | PROCESS_SET_QUOTA, false, processId);
        if (process == IntPtr.Zero)
        {
            return Marshal.GetLastWin32Error();
        }

        try
        {
            if (!AssignProcessToJobObject(job, process))
            {
                return Marshal.GetLastWin32Error();
            }

            return 0;
        }
        finally
        {
            CloseHandle(process);
        }
    }
}
'@
}

function New-DevProcessRoot {
    if (-not (Test-Path -LiteralPath $script:devProcessRoot)) {
        New-Item -ItemType Directory -Path $script:devProcessRoot -Force | Out-Null
    }
}

function Remove-DevProcessRoot {
    Remove-Item -LiteralPath $script:devProcessRoot -Recurse -Force -ErrorAction SilentlyContinue
}

function New-DevJobObject {
    if ($script:devJobObjectHandle -ne [IntPtr]::Zero) {
        return
    }

    Initialize-DevJobObjectSupport
    $script:devJobObjectHandle = [AIWorkflowDevJobObject]::CreateKillOnCloseJob("AI-bioworkflow-dev-$PID")
}

function Close-DevJobObject {
    if ($script:devJobObjectHandle -eq [IntPtr]::Zero) {
        return
    }

    [AIWorkflowDevJobObject]::CloseHandle($script:devJobObjectHandle) | Out-Null
    $script:devJobObjectHandle = [IntPtr]::Zero
}

function Get-DevJobProcessId {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][string]$PidFile
    )

    $deadline = (Get-Date).AddSeconds(10)
    while ((Get-Date) -lt $deadline) {
        if (Test-Path -LiteralPath $PidFile) {
            $rawProcessId = Get-Content -LiteralPath $PidFile -TotalCount 1 -ErrorAction SilentlyContinue
            $processId = 0
            if ([int]::TryParse($rawProcessId, [ref]$processId)) {
                if (Get-Process -Id $processId -ErrorAction SilentlyContinue) {
                    return $processId
                }
            }
        }

        Start-Sleep -Milliseconds 50
    }

    throw "Timed out waiting for $Name dev job process id."
}

function Register-DevJobForCleanup {
    param(
        [Parameter(Mandatory = $true)][object]$Job,
        [Parameter(Mandatory = $true)][string]$PidFile,
        [Parameter(Mandatory = $true)][string]$GateFile
    )

    New-DevJobObject
    $processId = Get-DevJobProcessId -Name $Job.Name -PidFile $PidFile
    $assignError = [AIWorkflowDevJobObject]::TryAssignProcessId($script:devJobObjectHandle, $processId)
    if ($assignError -eq 5) {
        Write-Warning "$($Job.Name) dev process ${processId} is already managed by another Windows Job Object; continuing without local job-object cleanup registration."
    }
    elseif ($assignError -ne 0) {
        $errorMessage = (New-Object System.ComponentModel.Win32Exception($assignError)).Message
        throw "Failed to register $($Job.Name) dev process ${processId} for cleanup: $errorMessage"
    }

    Set-Content -LiteralPath $GateFile -Value "assigned" -Encoding ascii
}

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

    $apiBaseHost = $ApiHost
    if ($apiBaseHost -eq "0.0.0.0") {
        $apiBaseHost = "127.0.0.1"
    }

    return "http://${apiBaseHost}:${ApiPort}"
}

function Get-WebCorsOrigins {
    if ($WebHost -eq "0.0.0.0") {
        $origins = @(
            "http://127.0.0.1:${WebPort}",
            "http://localhost:${WebPort}"
        )
    }
    else {
        $origins = @("http://${WebHost}:${WebPort}")
    }

    if ($WebHost -eq "127.0.0.1") {
        $origins += "http://localhost:${WebPort}"
    }
    elseif ($WebHost -eq "localhost") {
        $origins += "http://127.0.0.1:${WebPort}"
    }

    return (($origins | Select-Object -Unique) -join ",")
}

function Resolve-BindAddress {
    param([Parameter(Mandatory = $true)][string]$HostName)

    $address = [System.Net.IPAddress]::Any
    if ([System.Net.IPAddress]::TryParse($HostName, [ref]$address)) {
        return $address
    }

    try {
        $address = [System.Net.Dns]::GetHostAddresses($HostName) |
            Where-Object { $_.AddressFamily -eq [System.Net.Sockets.AddressFamily]::InterNetwork } |
            Select-Object -First 1
    }
    catch {
        throw "Host could not be resolved: $HostName"
    }

    if ($null -eq $address) {
        throw "Host did not resolve to an IPv4 address: $HostName"
    }

    return $address
}

function Test-TcpPortAvailable {
    param(
        [Parameter(Mandatory = $true)][string]$HostName,
        [Parameter(Mandatory = $true)][int]$Port
    )

    $listener = $null
    try {
        $address = Resolve-BindAddress -HostName $HostName
        $listener = [System.Net.Sockets.TcpListener]::new($address, $Port)
        $listener.Start()
        return [pscustomobject]@{
            Available = $true
            Reason = ""
            Message = ""
        }
    }
    catch [System.Net.Sockets.SocketException] {
        $reason = "BindFailed"
        if ($_.Exception.SocketErrorCode -eq [System.Net.Sockets.SocketError]::AddressAlreadyInUse) {
            $reason = "PortInUse"
        }
        elseif ($_.Exception.SocketErrorCode -eq [System.Net.Sockets.SocketError]::AddressNotAvailable) {
            $reason = "AddressNotAvailable"
        }

        return [pscustomobject]@{
            Available = $false
            Reason = $reason
            Message = $_.Exception.Message
        }
    }
    catch {
        return [pscustomobject]@{
            Available = $false
            Reason = "HostResolutionFailed"
            Message = $_.Exception.Message
        }
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

    $result = Test-TcpPortAvailable -HostName $HostName -Port $Port
    if ($result.Available) {
        return
    }

    if ($result.Reason -eq "HostResolutionFailed") {
        throw "$Name host could not be resolved for port check: $HostName. $($result.Message)"
    }
    elseif ($result.Reason -eq "AddressNotAvailable") {
        throw "$Name host is not available for binding: ${HostName}:${Port}. $($result.Message)"
    }
    elseif ($result.Reason -eq "PortInUse") {
        throw "$Name port is already in use: ${HostName}:${Port}. Pass a different port or use -SkipPortCheck if this is expected."
    }

    throw "$Name port check failed for ${HostName}:${Port}. $($result.Message)"
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

    New-DevProcessRoot
    $pidFile = Join-Path $script:devProcessRoot "api.pid"
    $gateFile = Join-Path $script:devProcessRoot "api.assigned"
    $job = Start-Job -Name "api" -ScriptBlock {
        param($RepoRoot, $PythonCommand, $ApiHost, $ApiPort, $CorsOrigins, $PidFile, $GateFile)

        $ErrorActionPreference = "Stop"
        Set-Content -LiteralPath $PidFile -Value ([string]$PID) -Encoding ascii
        $gateDeadline = (Get-Date).AddSeconds(10)
        while (-not (Test-Path -LiteralPath $GateFile)) {
            if ((Get-Date) -ge $gateDeadline) {
                throw "Timed out waiting for api cleanup registration gate."
            }
            Start-Sleep -Milliseconds 50
        }

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
    } -ArgumentList $repoRoot, $PythonCommand, $ApiHost, $ApiPort, $CorsOrigins, $pidFile, $gateFile

    try {
        Register-DevJobForCleanup -Job $job -PidFile $pidFile -GateFile $gateFile
        return $job
    }
    catch {
        Stop-Job -Job $job -ErrorAction SilentlyContinue
        Remove-Job -Job $job -Force -ErrorAction SilentlyContinue
        throw
    }
}

function Start-WebJob {
    param([Parameter(Mandatory = $true)][string]$ResolvedApiBaseUrl)

    New-DevProcessRoot
    $pidFile = Join-Path $script:devProcessRoot "web.pid"
    $gateFile = Join-Path $script:devProcessRoot "web.assigned"
    $job = Start-Job -Name "web" -ScriptBlock {
        param($WebRoot, $WebHost, $WebPort, $ResolvedApiBaseUrl, $PidFile, $GateFile)

        $ErrorActionPreference = "Stop"
        Set-Content -LiteralPath $PidFile -Value ([string]$PID) -Encoding ascii
        $gateDeadline = (Get-Date).AddSeconds(10)
        while (-not (Test-Path -LiteralPath $GateFile)) {
            if ((Get-Date) -ge $gateDeadline) {
                throw "Timed out waiting for web cleanup registration gate."
            }
            Start-Sleep -Milliseconds 50
        }

        Set-Location $WebRoot
        $env:NEXT_PUBLIC_API_BASE_URL = $ResolvedApiBaseUrl

        & npm run dev -- -H $WebHost -p $WebPort 2>&1 | ForEach-Object { "[web] $_" }
        if ($LASTEXITCODE -ne 0) {
            throw "Next.js dev server exited with code $LASTEXITCODE"
        }
    } -ArgumentList $webRoot, $WebHost, $WebPort, $ResolvedApiBaseUrl, $pidFile, $gateFile

    try {
        Register-DevJobForCleanup -Job $job -PidFile $pidFile -GateFile $gateFile
        return $job
    }
    catch {
        Stop-Job -Job $job -ErrorAction SilentlyContinue
        Remove-Job -Job $job -Force -ErrorAction SilentlyContinue
        throw
    }
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

$resolvedApiBaseUrl = Resolve-ApiBaseUrl
$corsOrigins = ""

if (-not $WebOnly) {
    Set-PythonCommand
    $corsOrigins = Get-WebCorsOrigins
}

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
    try {
        foreach ($job in $jobs) {
            Stop-Job -Job $job -ErrorAction SilentlyContinue
            Remove-Job -Job $job -Force -ErrorAction SilentlyContinue
        }
    }
    finally {
        Close-DevJobObject
        Remove-DevProcessRoot
    }
}

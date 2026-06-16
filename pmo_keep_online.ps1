param(
    [int]$Port = 8091,
    [int]$PlayzPort = 8092,
    [int]$CheckSeconds = 10,
    [string]$PythonExe = "C:\Users\mauri\AppData\Local\Programs\Python\Python314\python.exe"
)

$ErrorActionPreference = "Continue"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$PmoRoot = Split-Path -Parent $Root
$DesktopRoot = Split-Path -Parent $PmoRoot
$PlayzStandaloneRoot = Join-Path $DesktopRoot "PMO_Playz_Standalone"
$PlayzRoot = Join-Path $PlayzStandaloneRoot "PMO_PLAYZ_GROWTH_PANEL"
$LogDir = Join-Path $Root "pmo_runtime_logs"
$BotLogDir = Join-Path $LogDir "bot"
$PlayzLogDir = Join-Path $PlayzStandaloneRoot "PMO_Playz_Extras\pmo_runtime_logs\playz"
$WatchdogLog = Join-Path $LogDir "pmo_keep_online.log"
New-Item -ItemType Directory -Path $LogDir -Force | Out-Null
New-Item -ItemType Directory -Path $BotLogDir -Force | Out-Null
New-Item -ItemType Directory -Path $PlayzLogDir -Force | Out-Null

if (-not (Test-Path -LiteralPath $PythonExe)) {
    $PythonExe = "python"
}

function Write-PmoWatchdogLog {
    param([string]$Message)
    $stamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    Add-Content -LiteralPath $WatchdogLog -Value "[$stamp] $Message"
}

function Get-PmoBotProcesses {
    Get-CimInstance Win32_Process -Filter "Name = 'python.exe'" -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -match "(^|[\\\s`"'])pmo_bot\.py([`"'\s]|$)" }
}

function Get-PmoPlayzProcesses {
    Get-CimInstance Win32_Process -Filter "Name = 'python.exe'" -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -match "(^|[\\\s`"'])pmo_playz_platform\.py([`"'\s]|$)" }
}

function Test-PmoBotEndpoint {
    try {
        $response = Invoke-WebRequest -Uri "http://127.0.0.1:$Port/tradingview" -UseBasicParsing -TimeoutSec 5
        return [int]$response.StatusCode -eq 200
    } catch {
        return $false
    }
}

function Test-PmoPlayzEndpoint {
    try {
        $response = Invoke-WebRequest -Uri "http://127.0.0.1:$PlayzPort/api/health" -UseBasicParsing -TimeoutSec 5
        return [int]$response.StatusCode -eq 200
    } catch {
        return $false
    }
}

function Start-PmoDashboard {
    $stamp = Get-Date -Format "yyyyMMdd_HHmmss"
    $stdout = Join-Path $BotLogDir "pmo_watchdog_dashboard_$stamp.out.log"
    $stderr = Join-Path $BotLogDir "pmo_watchdog_dashboard_$stamp.err.log"
    Write-PmoWatchdogLog "Starting PMO BOT dashboard on port $Port"
    Start-Process -FilePath $PythonExe `
        -ArgumentList "pmo_bot.py" `
        -WorkingDirectory $Root `
        -RedirectStandardOutput $stdout `
        -RedirectStandardError $stderr `
        -WindowStyle Hidden | Out-Null
}

function Start-PmoPlayz {
    if (-not (Test-Path -LiteralPath (Join-Path $PlayzRoot "pmo_playz_platform.py"))) {
        Write-PmoWatchdogLog "PMO Playz script missing. playz_root=$PlayzRoot"
        return
    }
    $stdout = Join-Path $PlayzLogDir "pmo_playz_8092_stdout.log"
    $stderr = Join-Path $PlayzLogDir "pmo_playz_8092_stderr.log"
    Write-PmoWatchdogLog "Starting PMO Playz on port $PlayzPort root=$PlayzRoot"
    Start-Process -FilePath $PythonExe `
        -ArgumentList "pmo_playz_platform.py" `
        -WorkingDirectory $PlayzRoot `
        -RedirectStandardOutput $stdout `
        -RedirectStandardError $stderr `
        -WindowStyle Hidden | Out-Null
}

function Ensure-PmoBotOnline {
    $endpointOk = Test-PmoBotEndpoint
    $listener = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1

    if ($endpointOk) {
        return
    }

    $botProcesses = @(Get-PmoBotProcesses)
    if ($listener) {
        $ownerPid = [int]$listener.OwningProcess
        $owner = Get-CimInstance Win32_Process -Filter "ProcessId=$ownerPid" -ErrorAction SilentlyContinue
        if ($owner -and $owner.CommandLine -match "pmo_bot\.py") {
            Write-PmoWatchdogLog "Port $Port is owned by stale PMO BOT process $ownerPid but health check failed; restarting it."
            Stop-Process -Id $ownerPid -Force -ErrorAction SilentlyContinue
            Start-Sleep -Seconds 2
            Start-PmoDashboard
            Start-Sleep -Seconds 20
        } else {
            Write-PmoWatchdogLog "Port $Port is occupied by a non-PMO process. owner=$ownerPid command=$($owner.CommandLine)"
        }
    } elseif ($botProcesses.Count -gt 0) {
        foreach ($proc in $botProcesses) {
            Write-PmoWatchdogLog "Found stale PMO BOT python process $($proc.ProcessId) without port listener; restarting."
            Stop-Process -Id ([int]$proc.ProcessId) -Force -ErrorAction SilentlyContinue
        }
        Start-Sleep -Seconds 2
        Start-PmoDashboard
        Start-Sleep -Seconds 20
    } else {
        Write-PmoWatchdogLog "PMO BOT dashboard is offline; starting it."
        Start-PmoDashboard
        Start-Sleep -Seconds 20
    }
}

function Ensure-PmoPlayzOnline {
    $endpointOk = Test-PmoPlayzEndpoint
    $listener = Get-NetTCPConnection -LocalPort $PlayzPort -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1

    if ($endpointOk) {
        return
    }

    $playzProcesses = @(Get-PmoPlayzProcesses)
    if ($listener) {
        $ownerPid = [int]$listener.OwningProcess
        $owner = Get-CimInstance Win32_Process -Filter "ProcessId=$ownerPid" -ErrorAction SilentlyContinue
        if ($owner -and $owner.CommandLine -match "pmo_playz_platform\.py") {
            Write-PmoWatchdogLog "Port $PlayzPort is owned by stale PMO Playz process $ownerPid but health check failed; restarting it."
            Stop-Process -Id $ownerPid -Force -ErrorAction SilentlyContinue
            Start-Sleep -Seconds 2
            Start-PmoPlayz
            Start-Sleep -Seconds 12
        } else {
            Write-PmoWatchdogLog "Port $PlayzPort is occupied by a non-PMO Playz process. owner=$ownerPid command=$($owner.CommandLine)"
        }
    } elseif ($playzProcesses.Count -gt 0) {
        foreach ($proc in $playzProcesses) {
            Write-PmoWatchdogLog "Found stale PMO Playz python process $($proc.ProcessId) without port listener; restarting."
            Stop-Process -Id ([int]$proc.ProcessId) -Force -ErrorAction SilentlyContinue
        }
        Start-Sleep -Seconds 2
        Start-PmoPlayz
        Start-Sleep -Seconds 12
    } else {
        Write-PmoWatchdogLog "PMO Playz is offline; starting it."
        Start-PmoPlayz
        Start-Sleep -Seconds 12
    }
}

Write-PmoWatchdogLog "PMO keep-online watchdog started. root=$Root port=$Port playz_root=$PlayzRoot playz_port=$PlayzPort check_seconds=$CheckSeconds python=$PythonExe"

while ($true) {
    try {
        Ensure-PmoBotOnline
        Ensure-PmoPlayzOnline
    } catch {
        Write-PmoWatchdogLog "Watchdog error: $($_.Exception.Message)"
    }

    Start-Sleep -Seconds $CheckSeconds
}

param(
    [string]$HostUrl = "http://127.0.0.1:8091",
    [switch]$StartIfOffline,
    [switch]$NoPrompt,
    [string]$AdminToken = "",
    [switch]$RunSmokeTests,
    [switch]$RunFreshAiScoreAudit,
    [switch]$OpenReportFolder
)

$ErrorActionPreference = "Continue"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$ReportRoot = Join-Path $Root "pmo_reports"
$AuditRoot = Join-Path $ReportRoot "manual_audits"
$CsvDir = Join-Path $Root "pmo_csv"
$JournalFile = Join-Path $CsvDir "pmo_bot_trade_journal.csv"
$Timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$OutDir = Join-Path $AuditRoot "PMO_AUDIT_$Timestamp"
$SummaryFile = Join-Path $OutDir "PMO_AUDIT_SUMMARY.txt"
$TranscriptFile = Join-Path $OutDir "PMO_AUDIT_TRANSCRIPT.log"

New-Item -ItemType Directory -Force -Path $OutDir | Out-Null

function Write-Line {
    param([string]$Text = "")
    Write-Host $Text
    Add-Content -LiteralPath $SummaryFile -Value $Text
}

function Save-Text {
    param(
        [string]$Name,
        [string]$Text
    )
    $path = Join-Path $OutDir $Name
    $Text | Out-File -LiteralPath $path -Encoding UTF8
    return $path
}

function Save-Json {
    param(
        [string]$Name,
        [object]$Object
    )
    $path = Join-Path $OutDir $Name
    $Object | ConvertTo-Json -Depth 40 | Out-File -LiteralPath $path -Encoding UTF8
    return $path
}

function Convert-SecureStringToPlain {
    param([System.Security.SecureString]$Secure)
    if (-not $Secure -or $Secure.Length -eq 0) { return "" }
    $bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($Secure)
    try {
        return [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr)
    } finally {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr)
    }
}

function Invoke-PmoApi {
    param(
        [string]$Name,
        [string]$Method = "GET",
        [string]$Path,
        [object]$Body = $null,
        [bool]$UseAdmin = $false,
        [int]$TimeoutSec = 90
    )

    $safeName = ($Name -replace '[^A-Za-z0-9_.-]', '_')
    $uri = "$HostUrl$Path"
    $headers = @{}
    if ($UseAdmin -and $script:AdminToken) {
        $headers["X-PMO-BOT-ADMIN-TOKEN"] = $script:AdminToken
    }

    $result = [ordered]@{
        ok = $false
        name = $Name
        method = $Method
        path = $Path
        uri = $uri
        used_admin_token = [bool]($UseAdmin -and $script:AdminToken)
        timestamp = (Get-Date).ToString("o")
    }

    try {
        if ($Method.ToUpperInvariant() -eq "POST") {
            $jsonBody = "{}"
            if ($null -ne $Body) {
                $jsonBody = ($Body | ConvertTo-Json -Depth 20)
            }
            $payload = Invoke-RestMethod -UseBasicParsing -Uri $uri -Method POST -ContentType "application/json" -Headers $headers -Body $jsonBody -TimeoutSec $TimeoutSec
        } else {
            $payload = Invoke-RestMethod -UseBasicParsing -Uri $uri -Method GET -Headers $headers -TimeoutSec $TimeoutSec
        }
        $result.ok = $true
        $result.response = $payload
        Save-Json "$safeName.json" $result | Out-Null
        Write-Host ("[OK]   {0}" -f $Name) -ForegroundColor Green
        return $result
    } catch {
        $result.error = $_.Exception.Message
        if ($_.ErrorDetails -and $_.ErrorDetails.Message) {
            $result.error_detail = $_.ErrorDetails.Message
        }
        Save-Json "$safeName.ERROR.json" $result | Out-Null
        Write-Host ("[FAIL] {0}: {1}" -f $Name, $_.Exception.Message) -ForegroundColor Yellow
        return $result
    }
}

function Test-PmoOnline {
    try {
        $health = Invoke-RestMethod -UseBasicParsing -Uri "$HostUrl/api/health" -TimeoutSec 8
        return [bool]$health.ok
    } catch {
        return $false
    }
}

function Save-SkippedReport {
    param(
        [string]$Name,
        [string]$Reason
    )
    $safeName = ($Name -replace '[^A-Za-z0-9_.-]', '_')
    $result = [ordered]@{
        ok = $false
        skipped = $true
        name = $Name
        reason = $Reason
        timestamp = (Get-Date).ToString("o")
    }
    Save-Json "$safeName.SKIPPED.json" $result | Out-Null
    Write-Host ("[SKIP] {0}: {1}" -f $Name, $Reason) -ForegroundColor Yellow
    return $result
}

function Start-PmoIfNeeded {
    if (Test-PmoOnline) {
        Write-Host "PMO API is online." -ForegroundColor Green
        return
    }
    if (-not $StartIfOffline) {
        Write-Host "PMO API is offline. Start PMO first or rerun with StartIfOffline." -ForegroundColor Yellow
        return
    }
    $botPath = Join-Path $Root "pmo_bot.py"
    if (-not (Test-Path -LiteralPath $botPath)) {
        Write-Host "pmo_bot.py was not found: $botPath" -ForegroundColor Red
        return
    }
    $stdout = Join-Path $Root ("pmo_runtime_stdout_audit_$Timestamp.log")
    $stderr = Join-Path $Root ("pmo_runtime_stderr_audit_$Timestamp.log")
    Write-Host "PMO API is offline. Starting PMO on port 8091..." -ForegroundColor Yellow
    Start-Process -FilePath "python" -ArgumentList @("-B", $botPath) -WorkingDirectory $Root -RedirectStandardOutput $stdout -RedirectStandardError $stderr -WindowStyle Hidden | Out-Null
    for ($i = 1; $i -le 12; $i++) {
        Start-Sleep -Seconds 5
        if (Test-PmoOnline) {
            Write-Host "PMO API came online." -ForegroundColor Green
            return
        }
        Write-Host "Waiting for PMO API... $($i * 5)s"
    }
    Write-Host "PMO did not come online within 60 seconds. Continuing with local-only reports." -ForegroundColor Yellow
}

Start-Transcript -LiteralPath $TranscriptFile -Force | Out-Null

try {
    Write-Line "============================================================"
    Write-Line "PMO AUDITS AND REPORTS"
    Write-Line "Started: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"
    Write-Line "Host: $HostUrl"
    Write-Line "Root: $Root"
    Write-Line "Output: $OutDir"
    Write-Line "Prompt mode: $(if ($NoPrompt) { 'NO PROMPTS' } else { 'INTERACTIVE' })"
    Write-Line "Live trading changes: NONE"
    Write-Line "Order submission: NONE"
    Write-Line "============================================================"
    Write-Line ""

    Start-PmoIfNeeded

    if ($NoPrompt) {
        $script:AdminToken = $AdminToken
    } else {
        $secureToken = Read-Host "Optional PMO admin token for admin-only reports. Press Enter to skip" -AsSecureString
        $script:AdminToken = Convert-SecureStringToPlain $secureToken
    }
    if ($script:AdminToken) {
        Write-Line "Admin token: PROVIDED for this run only. It is not written to report files."
    } else {
        Write-Line "Admin token: skipped. Admin-only reports will use cached/read-only fallbacks."
    }
    Write-Line ""

    Write-Line "API REPORTS"
    Write-Line "-----------"
    $health = Invoke-PmoApi -Name "01_health" -Path "/api/health" -TimeoutSec 30
    $status = Invoke-PmoApi -Name "02_status" -Path "/api/status" -TimeoutSec 60
    $tradeTruth = Invoke-PmoApi -Name "03_trade_truth" -Path "/api/trade-truth" -TimeoutSec 60
    $whyNot = Invoke-PmoApi -Name "04_why_not" -Path "/api/why-not" -TimeoutSec 90
    $paperDiagnosis = Invoke-PmoApi -Name "05_paper_proof_diagnosis" -Method "POST" -Path "/api/paper-proof/diagnosis" -Body @{ limit = 5000 } -TimeoutSec 120
    if ($script:AdminToken) {
        $fullSystem = Invoke-PmoApi -Name "06_full_system_test_ADMIN" -Method "POST" -Path "/api/full-system-test" -Body @{ record = $true } -UseAdmin $true -TimeoutSec 120
    } else {
        $fullSystem = Save-SkippedReport -Name "06_full_system_test" -Reason "admin token not provided"
    }
    $routeAudit = Invoke-PmoApi -Name "07_route_audit" -Path "/api/v2055/route-audit" -TimeoutSec 60
    $moduleReport = Invoke-PmoApi -Name "08_module_report" -Path "/api/v206/module-report" -TimeoutSec 60
    $scoreAuditCached = Invoke-PmoApi -Name "09_score_audit_cached" -Path "/api/score/audit" -TimeoutSec 60
    $regimeAdvisor = Invoke-PmoApi -Name "10_regime_advisor" -Path "/api/regime/advisor" -TimeoutSec 90
    $intelligenceReports = Invoke-PmoApi -Name "11_intelligence_reports" -Path "/api/intelligence/reports" -TimeoutSec 60
    $tradeReplay = Invoke-PmoApi -Name "12_trade_replay" -Path "/api/trade-replay?limit=500" -TimeoutSec 90

    if ($script:AdminToken) {
        $runFreshAuditNow = $false
        if ($NoPrompt) {
            $runFreshAuditNow = [bool]$RunFreshAiScoreAudit
        } else {
            $runAiAudit = Read-Host "Run fresh AI score audit now? This may call Claude/API credits. Type YES to run"
            $runFreshAuditNow = ($runAiAudit -eq "YES")
        }
        if ($runFreshAuditNow) {
            Invoke-PmoApi -Name "13_score_audit_fresh_ADMIN" -Method "POST" -Path "/api/score/audit" -Body @{ record = $true } -UseAdmin $true -TimeoutSec 180 | Out-Null
        } else {
            Write-Line "Fresh AI score audit: skipped."
        }
    } else {
        Write-Line "Fresh AI score audit: skipped because no admin token was provided."
    }

    Write-Line ""
    Write-Line "LOCAL REPORTS"
    Write-Line "-------------"

    $compilePath = Join-Path $OutDir "20_py_compile.txt"
    Write-Host "Running Python compile check..."
    Push-Location $Root
    try {
        python -m py_compile "pmo_bot.py" "pmo_settings.py" "pmo_sharpe.py" "pmo_async_audit.py" *> $compilePath
        $compileExit = $LASTEXITCODE
    } finally {
        Pop-Location
    }
    Write-Line "Python compile check exit code: $compileExit"
    Write-Line "Compile output: $compilePath"

    $blocklistOut = Join-Path $OutDir "21_blocklist_analysis.txt"
    if (Test-Path -LiteralPath (Join-Path $Root "pmo_blocklist_analysis.py")) {
        Write-Host "Running blocklist analysis..."
        Push-Location $Root
        try {
            python "pmo_blocklist_analysis.py" "$JournalFile" *> $blocklistOut
            $blockExit = $LASTEXITCODE
        } finally {
            Pop-Location
        }
        Write-Line "Blocklist analysis exit code: $blockExit"
        Write-Line "Blocklist output: $blocklistOut"
    } else {
        Write-Line "Blocklist analysis skipped: pmo_blocklist_analysis.py not found."
    }

    $riskOut = Join-Path $OutDir "22_risk_adjusted_metrics.txt"
    $riskJson = Join-Path $OutDir "22_risk_adjusted_metrics.json"
    if (Test-Path -LiteralPath (Join-Path $Root "pmo_sharpe.py")) {
        Write-Host "Running risk-adjusted metrics..."
        Push-Location $Root
        try {
            python "pmo_sharpe.py" "$JournalFile" --json-output "$riskJson" *> $riskOut
            $riskExit = $LASTEXITCODE
        } finally {
            Pop-Location
        }
        Write-Line "Risk-adjusted metrics exit code: $riskExit"
        Write-Line "Risk metrics output: $riskOut"
        Write-Line "Risk metrics JSON: $riskJson"
    } else {
        Write-Line "Risk-adjusted metrics skipped: pmo_sharpe.py not found."
    }

    $asyncOut = Join-Path $OutDir "23_async_order_audit.txt"
    $asyncJson = Join-Path $OutDir "23_async_order_audit.json"
    if (Test-Path -LiteralPath (Join-Path $Root "pmo_async_audit.py")) {
        Write-Host "Running async order-path audit..."
        Push-Location $Root
        try {
            python "pmo_async_audit.py" "pmo_bot.py" --json-output "$asyncJson" *> $asyncOut
            $asyncExit = $LASTEXITCODE
        } finally {
            Pop-Location
        }
        Write-Line "Async order audit exit code: $asyncExit"
        Write-Line "Async order audit output: $asyncOut"
        Write-Line "Async order audit JSON: $asyncJson"
    } else {
        Write-Line "Async order audit skipped: pmo_async_audit.py not found."
    }

    $runSmokeNow = $false
    if ($NoPrompt) {
        $runSmokeNow = [bool]$RunSmokeTests
    } else {
        $runSmoke = Read-Host "Run full smoke tests too? Takes about 30-60 seconds. Type YES to run"
        $runSmokeNow = ($runSmoke -eq "YES")
    }
    if ($runSmokeNow) {
        $smokeOut = Join-Path $OutDir "24_smoke_tests.txt"
        Write-Host "Running smoke tests..."
        Push-Location $Root
        try {
            & (Join-Path $Root "Run PMO BOT Smoke Tests.bat") *> $smokeOut
            $smokeExit = $LASTEXITCODE
        } finally {
            Pop-Location
        }
        Write-Line "Smoke tests exit code: $smokeExit"
        Write-Line "Smoke output: $smokeOut"
    } else {
        Write-Line "Smoke tests: skipped."
    }

    Write-Line ""
    Write-Line "KEY METRICS"
    Write-Line "-----------"
    try {
        $pp = $status.response.paper_proof
        if ($pp) {
            Write-Line ("Proof source: {0}" -f $pp.proof_source)
            Write-Line ('Clean proof: {0} closed | WR {1:P2} | PF {2} | Net ${3}' -f $pp.closed_trades, [double]$pp.win_rate, $pp.profit_factor, $pp.net_pnl)
            Write-Line ("Clean proof ready: {0} | Clean proof score: {1}" -f $pp.clean_proof_ready, $pp.clean_proof_score)
            if ($pp.raw_journal_summary) {
                Write-Line ("Raw journal: {0} closed | WR {1:P2} | PF {2}" -f $pp.raw_journal_summary.closed_trades, [double]$pp.raw_journal_summary.win_rate, $pp.raw_journal_summary.profit_factor)
            }
        }
    } catch {
        Write-Line "Proof metric summary failed: $($_.Exception.Message)"
    }
    try {
        $truth = $tradeTruth.response
        if ($truth) {
            Write-Line ("Trade truth: verdict {0} | missing {1} | warn {2} | readiness {3}" -f $truth.verdict, $truth.missing, $truth.warn, $truth.readiness_score)
            if ($truth.journal) {
                Write-Line ("Trade truth journal: {0} closed | WR {1:P2} | PF {2}" -f $truth.journal.closed, [double]$truth.journal.win_rate, $truth.journal.profit_factor)
            }
        }
    } catch {
        Write-Line "Trade truth summary failed: $($_.Exception.Message)"
    }
    try {
        $why = $whyNot.response.why_not.summary
        if ($why) {
            Write-Line ("Why-Not: {0} blocked | {1} ready | top blocker: {2}" -f $why.blocked, $why.ready, $why.top_blocker)
        }
    } catch {
        Write-Line "Why-Not summary failed: $($_.Exception.Message)"
    }
    try {
        if ($riskJson -and (Test-Path -LiteralPath $riskJson)) {
            $risk = Get-Content -LiteralPath $riskJson -Raw | ConvertFrom-Json
            $cleanRisk = $risk.clean
            if ($cleanRisk -and $cleanRisk.ok) {
                Write-Line ('Clean risk metrics: Sharpe {0} | Sortino {1} | Max DD ${2} | Recovery {3}' -f $cleanRisk.sharpe, $cleanRisk.sortino, $cleanRisk.max_drawdown, $cleanRisk.recovery_factor)
            }
        }
    } catch {
        Write-Line "Risk metric summary failed: $($_.Exception.Message)"
    }
    try {
        if ($asyncJson -and (Test-Path -LiteralPath $asyncJson)) {
            $async = Get-Content -LiteralPath $asyncJson -Raw | ConvertFrom-Json
            Write-Line ("Async audit: {0} findings | {1} hot path | {2} critical hot path" -f $async.findings_total, $async.hot_path_findings, $async.critical_hot_path_findings)
        }
    } catch {
        Write-Line "Async audit summary failed: $($_.Exception.Message)"
    }

    Write-Line ""
    Write-Line "Finished: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"
    Write-Line "Output folder: $OutDir"

    $openFolderNow = $false
    if ($NoPrompt) {
        $openFolderNow = [bool]$OpenReportFolder
    } else {
        $openFolder = Read-Host "Open report folder now? Type YES to open"
        $openFolderNow = ($openFolder -eq "YES")
    }
    if ($openFolderNow) {
        Start-Process explorer.exe $OutDir | Out-Null
    }
} finally {
    if ($script:AdminToken) {
        $script:AdminToken = $null
    }
    Stop-Transcript | Out-Null
}

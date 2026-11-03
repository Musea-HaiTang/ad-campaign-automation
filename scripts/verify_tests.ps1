[CmdletBinding()]
param(
    [ValidateSet("auto", "full", "by-file")]
    [string]$Mode = "auto",
    [string]$Output = ""
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$VenvPython = Join-Path $RepoRoot ".venv\Scripts\python.exe"
$TestsDir = Join-Path $RepoRoot "automation\tests"
$ReportDir = Join-Path $RepoRoot "automation\_tmp\pytest-reports"

if (-not $Output) {
    $Output = Join-Path $RepoRoot ".local\test-results.json"
} elseif (-not [System.IO.Path]::IsPathRooted($Output)) {
    $Output = Join-Path $RepoRoot $Output
}

function Invoke-PytestReport {
    param(
        [string]$ReportPath,
        [string[]]$Targets
    )

    Remove-Item -LiteralPath $ReportPath -Force -ErrorAction SilentlyContinue
    try {
        & $VenvPython -m pytest -q @Targets "--junitxml=$ReportPath" 2>&1 | Out-Null
    } catch {
    }
    if (-not (Test-Path -LiteralPath $ReportPath)) {
        return [pscustomobject]@{
            status = "failed"
            tests = 1
            passed = 0
            failed = 1
            errors = 0
            skipped = 0
            failures = @("pytest 未生成结果文件")
        }
    }

    [xml]$report = Get-Content -LiteralPath $ReportPath -Raw
    $suites = @($report.SelectNodes(
        '/*[local-name()="testsuites"]/*[local-name()="testsuite"] | /*[local-name()="testsuite"]'
    ))
    $tests = 0
    $failed = 0
    $errors = 0
    $skipped = 0
    foreach ($suite in $suites) {
        $tests += [int]$suite.tests
        $failed += [int]$suite.failures
        $errors += [int]$suite.errors
        $skipped += [int]$suite.skipped
    }
    $failureNodes = @($report.SelectNodes(
        '//testcase[failure or error]'
    ))
    $failureNames = @($failureNodes | ForEach-Object {
        (([string]$_.classname) + "::" + ([string]$_.name)).Trim(":")
    })
    $passed = [Math]::Max(0, $tests - $failed - $errors - $skipped)
    return [pscustomobject]@{
        status = if ($failed -eq 0 -and $errors -eq 0) { "ok" } else { "failed" }
        tests = $tests
        passed = $passed
        failed = $failed
        errors = $errors
        skipped = $skipped
        failures = $failureNames
    }
}

if (-not (Test-Path -LiteralPath $VenvPython)) {
    throw "找不到虚拟环境 Python：$VenvPython"
}
New-Item -ItemType Directory -Force -Path $ReportDir | Out-Null

$modeReason = "命令行指定"
if ($Mode -eq "auto") {
    $safeDelete = @(Get-ChildItem Env: | Where-Object {
        $_.Name -like "CODEBUDDY_SAFE_DELETE_*"
    })
    if ($safeDelete.Count -gt 0) {
        $Mode = "by-file"
        $modeReason = "检测到 WorkBuddy 安全删除垫片环境"
    } else {
        $Mode = "full"
        $modeReason = "未检测到 WorkBuddy 安全删除垫片环境"
    }
}

$results = @()
if ($Mode -eq "full") {
    Write-Host "  RUN automation/tests"
    $reportPath = Join-Path $ReportDir "all.xml"
    $item = Invoke-PytestReport -ReportPath $reportPath -Targets @($TestsDir)
    $item | Add-Member -NotePropertyName path -NotePropertyValue "automation/tests"
    $results += $item
} else {
    $testFiles = @(Get-ChildItem -LiteralPath $TestsDir -File -Filter "test_*.py" |
        Sort-Object Name)
    foreach ($file in $testFiles) {
        Write-Host ("  RUN automation/tests/" + $file.Name)
        $reportPath = Join-Path $ReportDir ($file.BaseName + ".xml")
        $item = Invoke-PytestReport -ReportPath $reportPath -Targets @($file.FullName)
        $item | Add-Member -NotePropertyName path -NotePropertyValue (
            "automation/tests/" + $file.Name
        )
        $results += $item
    }
}

$summary = [ordered]@{
    passed = ($results | Measure-Object -Property passed -Sum).Sum
    failed = ($results | Measure-Object -Property failed -Sum).Sum
    errors = ($results | Measure-Object -Property errors -Sum).Sum
    skipped = ($results | Measure-Object -Property skipped -Sum).Sum
}
$ok = $results.Count -gt 0 -and @($results | Where-Object {
    $_.status -ne "ok"
}).Count -eq 0
$payload = [ordered]@{
    status = if ($ok) { "ok" } else { "failed" }
    mode = $Mode
    modeReason = $modeReason
    finishedAt = (Get-Date).ToString("o")
    summary = $summary
    results = $results
}

$outputDir = Split-Path -Parent $Output
New-Item -ItemType Directory -Force -Path $outputDir | Out-Null
[System.IO.File]::WriteAllText(
    $Output,
    ($payload | ConvertTo-Json -Depth 8),
    (New-Object System.Text.UTF8Encoding($false))
)

Write-Host (
    "TEST_RESULT: {0} | mode={1} | passed={2} failed={3} errors={4} skipped={5}" -f
    $payload.status, $Mode, $summary.passed, $summary.failed, $summary.errors, $summary.skipped
)
Write-Host ("TEST_RESULT_FILE: " + $Output)

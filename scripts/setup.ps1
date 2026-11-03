[CmdletBinding()]
param(
    [string]$Owner = "",
    [string]$Python = "",
    [ValidateSet("auto", "edge", "chrome")]
    [string]$Browser = "auto",
    [switch]$RunTests
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $RepoRoot
$LocalDir = Join-Path $RepoRoot ".local"
$SetupResultPath = Join-Path $LocalDir "setup-result.json"
$CurrentStep = "启动"

try {
    New-Item -ItemType Directory -Force -Path $LocalDir | Out-Null
} catch {
}

function Write-Step {
    param([int]$Number, [int]$Total, [string]$Text)
    $script:CurrentStep = $Text
    Write-Host ""
    Write-Host ("[{0}/{1}] {2}" -f $Number, $Total, $Text) -ForegroundColor Cyan
}

function Write-Ok {
    param([string]$Text)
    Write-Host ("  OK: " + $Text) -ForegroundColor Green
}

function Write-Skip {
    param([string]$Text)
    Write-Host ("  SKIP: " + $Text) -ForegroundColor Yellow
}

function Write-SetupResult {
    param(
        [string]$Status,
        [string]$Message,
        $Tests = $null
    )
    try {
        $payload = [ordered]@{
            status = $Status
            message = $Message
            step = $script:CurrentStep
            repo = $RepoRoot
            finishedAt = (Get-Date).ToString("o")
            tests = $Tests
        }
        [System.IO.File]::WriteAllText(
            $script:SetupResultPath,
            ($payload | ConvertTo-Json -Depth 8),
            (New-Object System.Text.UTF8Encoding($false))
        )
    } catch {
    }
}

function Stop-Setup {
    param([string]$Text)
    Write-SetupResult -Status "failed" -Message $Text
    Write-Host ("  FAIL: " + $Text) -ForegroundColor Red
    Write-Host ""
    Write-Host "SETUP: FAILED" -ForegroundColor Red
    exit 1
}

function Invoke-PythonProbe {
    param(
        [string]$Command,
        [string]$Code,
        [string[]]$PrefixArgs = @(),
        [string[]]$Arguments = @()
    )
    $probe = Join-Path $script:LocalDir (
        "python-probe-" + [Guid]::NewGuid().ToString("N") + ".json"
    )
    try {
        & $Command @PrefixArgs -c $Code $probe @Arguments 2>$null | Out-Null
        if (-not (Test-Path -LiteralPath $probe)) {
            return $null
        }
        return Get-Content -LiteralPath $probe -Raw | ConvertFrom-Json
    } catch {
        return $null
    } finally {
        Remove-Item -LiteralPath $probe -Force -ErrorAction SilentlyContinue
    }
}

function Get-PythonInfo {
    param(
        [string]$Path,
        [string[]]$PrefixArgs = @()
    )

    try {
        $code = "import json,pathlib,sys; data={'version':'%d.%d.%d' % sys.version_info[:3],'executable':sys.executable}; pathlib.Path(sys.argv[1]).write_text(json.dumps(data),encoding='utf-8')"
        $data = Invoke-PythonProbe -Command $Path -Code $code -PrefixArgs $PrefixArgs
        if (-not $data -or -not $data.version) {
            return $null
        }
        $parts = ([string]$data.version).Split(".")
        return [pscustomobject]@{
            Path = [string]$data.executable
            Command = $Path
            Major = [int]$parts[0]
            Minor = [int]$parts[1]
            Patch = [int]$parts[2]
            Text = [string]$data.version
        }
    } catch {
        return $null
    }
}

function Test-CompatiblePython {
    param($Info)
    return $Info -and $Info.Major -eq 3 -and $Info.Minor -ge 12 -and $Info.Minor -le 14
}

function Resolve-BasePython {
    if ($Python) {
        $candidate = $Python
        if (-not (Test-Path -LiteralPath $candidate)) {
            $command = Get-Command $candidate -ErrorAction SilentlyContinue
            if ($command) {
                $candidate = $command.Source
            }
        }
        $info = Get-PythonInfo -Path $candidate
        if (-not (Test-CompatiblePython $info)) {
            Stop-Setup ("指定的 Python 不可用或版本不在 3.12-3.14 范围内: " + $Python)
        }
        return $info.Path
    }

    $candidates = @()
    $windowsApps = Join-Path $env:LOCALAPPDATA "Microsoft\WindowsApps"
    $pythonCommands = Get-Command python.exe -All -ErrorAction SilentlyContinue
    foreach ($pythonCommand in $pythonCommands) {
        if ($pythonCommand.Source -and
            -not $pythonCommand.Source.StartsWith(
                $windowsApps + [IO.Path]::DirectorySeparatorChar,
                [StringComparison]::OrdinalIgnoreCase
            )) {
            $candidates += $pythonCommand.Source
        }
    }

    $pyCommand = Get-Command py.exe -ErrorAction SilentlyContinue
    if ($pyCommand) {
        foreach ($version in @("3.12", "3.13", "3.11", "3.14")) {
            $info = Get-PythonInfo -Path $pyCommand.Source -PrefixArgs @("-$version")
            if (Test-CompatiblePython $info) {
                $candidates += $info.Path
            }
        }
    }

    foreach ($candidate in ($candidates | Select-Object -Unique)) {
        $info = Get-PythonInfo -Path $candidate
        if (Test-CompatiblePython $info) {
            return $info.Path
        }
    }

    Stop-Setup "没有找到可用的 Python 3.12-3.14（WindowsApps 的 python.exe 占位别名会被忽略）。请安装兼容版本，或使用 -Python <解释器路径> 指定。"
}

function Find-Browser {
    param([string]$Kind)

    $edgePaths = @()
    if (${env:ProgramFiles(x86)}) {
        $edgePaths += Join-Path ${env:ProgramFiles(x86)} "Microsoft\Edge\Application\msedge.exe"
    }
    if ($env:ProgramFiles) {
        $edgePaths += Join-Path $env:ProgramFiles "Microsoft\Edge\Application\msedge.exe"
    }

    $chromePaths = @()
    if ($env:ProgramFiles) {
        $chromePaths += Join-Path $env:ProgramFiles "Google\Chrome\Application\chrome.exe"
    }
    if (${env:ProgramFiles(x86)}) {
        $chromePaths += Join-Path ${env:ProgramFiles(x86)} "Google\Chrome\Application\chrome.exe"
    }
    if ($env:LOCALAPPDATA) {
        $chromePaths += Join-Path $env:LOCALAPPDATA "Google\Chrome\Application\chrome.exe"
    }

    $groups = @()
    if ($Kind -eq "edge" -or $Kind -eq "auto") {
        $groups += [pscustomobject]@{ Name = "Edge"; Paths = $edgePaths }
    }
    if ($Kind -eq "chrome" -or $Kind -eq "auto") {
        $groups += [pscustomobject]@{ Name = "Chrome"; Paths = $chromePaths }
    }

    foreach ($group in $groups) {
        foreach ($path in $group.Paths) {
            if (Test-Path -LiteralPath $path) {
                return [pscustomobject]@{ Name = $group.Name; Path = $path }
            }
        }
    }
    return $null
}

function Get-ConfiguredBrowser {
    $configPath = Join-Path $RepoRoot ".local\browser.json"
    if (-not (Test-Path -LiteralPath $configPath)) {
        return $null
    }
    try {
        $saved = Get-Content -LiteralPath $configPath -Raw | ConvertFrom-Json
        if ($saved.path -and (Test-Path -LiteralPath $saved.path)) {
            return [pscustomobject]@{ Name = [string]$saved.kind; Path = [string]$saved.path }
        }
    } catch {
    }
    return $null
}

function Save-BrowserConfig {
    param($Info)
    $localDir = Join-Path $RepoRoot ".local"
    New-Item -ItemType Directory -Force -Path $localDir | Out-Null
    $configPath = Join-Path $localDir "browser.json"
    $data = [ordered]@{ kind = $Info.Name; path = $Info.Path }
    $json = $data | ConvertTo-Json
    [System.IO.File]::WriteAllText($configPath, $json, (New-Object System.Text.UTF8Encoding($false)))
}

Write-Host "CSDN 广告投放自动化 - 一键部署"
Write-Host ("项目目录: " + $RepoRoot)

$TotalSteps = if ($RunTests) { 9 } else { 8 }

Write-Step 1 $TotalSteps "检查 Python"
$VenvPython = Join-Path $RepoRoot ".venv\Scripts\python.exe"
if (Test-Path -LiteralPath $VenvPython) {
    $venvInfo = Get-PythonInfo -Path $VenvPython
    if (-not (Test-CompatiblePython $venvInfo)) {
        Stop-Setup "已有 .venv 的 Python 版本不在 3.12-3.14 范围内。请改名或删除 .venv 后重试；脚本不会自动删除已有环境。"
    }
    Write-Skip (".venv 已存在，复用 Python " + $venvInfo.Text)
} else {
    $BasePython = Resolve-BasePython
    $baseInfo = Get-PythonInfo -Path $BasePython
    Write-Ok ("使用 Python " + $baseInfo.Text + " (" + $BasePython + ")")
}

Write-Step 2 $TotalSteps "创建或复用虚拟环境"
if (-not (Test-Path -LiteralPath $VenvPython)) {
    try {
        & $BasePython -m venv (Join-Path $RepoRoot ".venv")
    } catch {
        Stop-Setup "创建 .venv 失败。"
    }
    $venvInfo = Get-PythonInfo -Path $VenvPython
    if (-not (Test-CompatiblePython $venvInfo)) {
        Stop-Setup "创建 .venv 后无法读取兼容的 Python 版本。"
    }
    Write-Ok ".venv 已创建"
} else {
    Write-Skip ".venv 已存在，未覆盖"
}

Write-Step 3 $TotalSteps "安装并检查 Python 依赖"
$Requirements = Join-Path $RepoRoot "requirements.txt"
try {
    & $VenvPython -m pip install --disable-pip-version-check -r $Requirements
} catch {
    Stop-Setup "安装 requirements.txt 失败。"
}
$depsCode = "import json,pathlib,sys; import yaml,playwright,pytest; import importlib.metadata as m; data={'PyYAML':m.version('PyYAML'),'playwright':m.version('playwright'),'pytest':m.version('pytest')}; pathlib.Path(sys.argv[1]).write_text(json.dumps(data),encoding='utf-8')"
$deps = Invoke-PythonProbe -Command $VenvPython -Code $depsCode
if (-not $deps) {
    Stop-Setup "Python 依赖导入检查失败。"
}
Write-Ok ("PyYAML " + $deps.PyYAML + " / Playwright " + $deps.playwright + " / pytest " + $deps.pytest)

Write-Step 4 $TotalSteps "检测浏览器"
$BrowserInfo = $null
if ($Browser -eq "auto") {
    $BrowserInfo = Get-ConfiguredBrowser
}
if (-not $BrowserInfo) {
    $BrowserInfo = Find-Browser -Kind $Browser
}
if (-not $BrowserInfo) {
    Stop-Setup ("没有找到请求的浏览器: " + $Browser + "。请安装 Edge 或 Chrome，或使用 -Browser edge/chrome 指定。")
}
Save-BrowserConfig -Info $BrowserInfo
Write-Ok ($BrowserInfo.Name + ": " + $BrowserInfo.Path)

Write-Step 5 $TotalSteps "创建运行目录"
$Directories = @(
    (Join-Path $RepoRoot "activities\_db"),
    (Join-Path $RepoRoot "activities\_db\backups"),
    (Join-Path $RepoRoot "automation\_tmp"),
    (Join-Path $RepoRoot ".browser-profile"),
    (Join-Path $RepoRoot ".local")
)
foreach ($directory in $Directories) {
    New-Item -ItemType Directory -Force -Path $directory | Out-Null
}

$WriteProbe = Join-Path $RepoRoot ".local\.write-test"
try {
    [System.IO.File]::WriteAllText($WriteProbe, "ok")
    Remove-Item -LiteralPath $WriteProbe -Force
} catch {
    Stop-Setup ("项目目录不可写: " + $RepoRoot)
}
Write-Ok "运行目录和写权限正常"

Write-Step 6 $TotalSteps "初始化数据库"
$Database = Join-Path $RepoRoot "activities\_db\投放数据.db"
if (Test-Path -LiteralPath $Database) {
    Write-Skip "数据库已存在，未覆盖"
} else {
    $dbCode = "import json,os,pathlib,sys; sys.path.insert(0,os.path.join(os.getcwd(),'automation','scripts')); import workspace_repo; conn=workspace_repo.connect(sys.argv[2]); version=conn.execute('SELECT MAX(version) FROM schema_version').fetchone()[0]; conn.close(); pathlib.Path(sys.argv[1]).write_text(json.dumps({'schemaVersion':version}),encoding='utf-8')"
    $dbResult = Invoke-PythonProbe -Command $VenvPython -Code $dbCode -Arguments @($Database)
    if (-not $dbResult) {
        Stop-Setup "数据库初始化失败。"
    }
    Write-Ok ("数据库已创建，schema v" + $dbResult.schemaVersion)
}

Write-Step 7 $TotalSteps "保存本地操作者配置"
$OperatorConfig = Join-Path $RepoRoot ".local\operator.json"
if (Test-Path -LiteralPath $OperatorConfig) {
    try {
        $existing = Get-Content -LiteralPath $OperatorConfig -Raw | ConvertFrom-Json
        if (-not $existing.owner) {
            Stop-Setup ".local\operator.json 已存在但没有 owner。请修正该文件后重试。"
        }
        Write-Skip ("操作者配置已存在，owner=" + $existing.owner)
    } catch {
        Stop-Setup ".local\operator.json 不是有效 JSON，或无法读取。"
    }
} else {
    if (-not $Owner) {
        Write-Host "首次部署需要设置负责人标识 owner。"
        Write-Host "用途：方便识别、查找和生成新活动的名称；不会修改已有活动。"
        Write-Host "示例：hang"
        $Owner = Read-Host "请输入你的 owner"
    }
    $Owner = ([string]$Owner).Trim()
    if (-not $Owner -or $Owner -match '[\\/:*?"<>|\s]') {
        Stop-Setup "owner 不能为空，且不能包含空格或路径保留字符。"
    }
    $data = [ordered]@{
        owner = $Owner
        ad_username = $null
    }
    $json = $data | ConvertTo-Json
    [System.IO.File]::WriteAllText($OperatorConfig, $json, (New-Object System.Text.UTF8Encoding($false)))
    Write-Ok ("操作者配置已创建，owner=" + $Owner)
}

Write-Step 8 $TotalSteps "初始化首次体验示例"
try {
    & $VenvPython (Join-Path $RepoRoot "scripts\demo.py") --db $Database
} catch {
    Stop-Setup "示例活动初始化失败。"
}
$demoCode = "import json,pathlib,sys; sys.path.insert(0,str(pathlib.Path.cwd() / 'automation' / 'scripts')); import workspace_repo; conn=workspace_repo.connect(sys.argv[2]); count=conn.execute('SELECT COUNT(*) FROM activity').fetchone()[0]; conn.close(); pathlib.Path(sys.argv[1]).write_text(json.dumps({'activityCount':count}),encoding='utf-8')"
$demoResult = Invoke-PythonProbe -Command $VenvPython -Code $demoCode -Arguments @($Database)
if (-not $demoResult -or [int]$demoResult.activityCount -lt 1) {
    Stop-Setup "示例活动初始化失败。"
}

$Tests = $null
if ($RunTests) {
    Write-Step 9 $TotalSteps "运行自动化测试"
    $TestResultPath = Join-Path $LocalDir "test-results.json"
    $VerifyScript = Join-Path $RepoRoot "scripts\verify_tests.ps1"
    try {
        & $VerifyScript -Mode auto -Output $TestResultPath
    } catch {
        Stop-Setup "自动化测试启动失败。"
    }
    if (-not (Test-Path -LiteralPath $TestResultPath)) {
        Stop-Setup "自动化测试未生成结果文件。"
    }
    $Tests = Get-Content -LiteralPath $TestResultPath -Raw | ConvertFrom-Json
    if ($Tests.status -ne "ok") {
        Stop-Setup ("自动化测试失败，详情见 " + $TestResultPath)
    }
    Write-Ok ("自动化测试通过（模式：" + $Tests.mode + "）")
}

Write-Host ""
Write-SetupResult -Status "ok" -Message "部署完成" -Tests $Tests
Write-Host "SETUP: OK" -ForegroundColor Green
Write-Host ("部署结果: " + $SetupResultPath)
Write-Host "下一步：.venv\Scripts\python.exe scripts\doctor.py --login"

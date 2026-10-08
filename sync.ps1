# sync.ps1 —— 把「工作仓库」里的**白名单文件**同步到本仓库（上传线），再交给你提交推送。
#
# 本仓库只放工具/代码/文档与模板；真实活动的配置、文案、物料、投放数据、台账库、登录态都不收录。
# 用法（在本目录下）：  powershell -ExecutionPolicy Bypass -File .\sync.ps1
param([string]$Src = 'D:\Codex_WorkingSpace\ad_management')

$dst = $PSScriptRoot
$paths = @('automation', 'web', 'ad_output', 'activities', 'requirements.txt', 'pytest.ini', 'AGENTS.md')
$exclude = '^(activities/[^/]+/(配置|调整|物料|日志)/|activities/[^/]+/数据/(?!README\.md$)|' +
           'activities/_验证数据/配置/|ad_output/memory/|_experiments/)'

$tracked = git -c core.quotepath=false -C $Src ls-files -- $paths
$keep = $tracked | Where-Object { $_ -notmatch $exclude }
$names = @('README.md', 'sync.ps1')          # 上传线自己的文件，不从工作仓库覆盖
$keep = $keep | Where-Object { $names -notcontains $_ }

foreach ($f in $keep) {
    $s = Join-Path $Src $f
    $t = Join-Path $dst $f
    New-Item -ItemType Directory -Force -Path (Split-Path $t) | Out-Null
    Copy-Item -LiteralPath $s -Destination $t -Force
}
Write-Output "已同步 $($keep.Count) 个文件（客户配置/文案/物料/数据未收录）"
git -C $dst add -A
git -C $dst status --short
Write-Output ''
Write-Output '核对无误后：'
Write-Output '  git commit -m "sync: 从工作仓库同步（工具/代码/文档/模板）"'
Write-Output '  git push'

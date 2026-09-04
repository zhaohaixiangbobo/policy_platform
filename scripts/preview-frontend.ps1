# 文件说明：启动生产构建预览，供Chrome 89和现代浏览器执行真实冒烟。
$ErrorActionPreference = 'Stop'
$repositoryPath = Join-Path $PSScriptRoot '..'

Set-Location -LiteralPath $repositoryPath
pnpm preview

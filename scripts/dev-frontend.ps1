# 文件说明：使用仓库冻结的pnpm版本启动本机Vite开发服务器。
$ErrorActionPreference = 'Stop'
$repositoryPath = Join-Path $PSScriptRoot '..'

Set-Location -LiteralPath $repositoryPath
pnpm dev

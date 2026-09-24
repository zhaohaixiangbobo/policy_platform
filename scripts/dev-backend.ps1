# 文件说明：使用固定py312解释器在127.0.0.1启动Platform API。
$ErrorActionPreference = 'Stop'
$pythonPath = 'D:\3-anaconda\envs\py312\python.exe'
$backendPath = Join-Path $PSScriptRoot '..\backend'

Set-Location -LiteralPath $backendPath
& $pythonPath (Join-Path $PSScriptRoot 'run-service.py') api --reload

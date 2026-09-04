# 文件说明：使用固定py312解释器在127.0.0.1启动Platform API。
$ErrorActionPreference = 'Stop'
$pythonPath = 'D:\3-anaconda\envs\py312\python.exe'
$backendPath = Join-Path $PSScriptRoot '..\backend'

Set-Location -LiteralPath $backendPath
& $pythonPath -m uvicorn app.main:app --host 127.0.0.1 --port 8020 --reload

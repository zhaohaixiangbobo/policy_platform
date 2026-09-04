# 文件说明：使用固定py312解释器启动第二期本机单Worker。
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$env:PYTHONPATH = Join-Path $projectRoot 'backend'
Set-Location (Join-Path $projectRoot 'backend')
& 'D:\3-anaconda\envs\py312\python.exe' worker.py

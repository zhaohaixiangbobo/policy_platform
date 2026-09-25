# 文件说明：固定py312解释器启动轻量学习自测Worker，与入库Worker分离。
$ErrorActionPreference = 'Stop'
& 'D:\3-anaconda\envs\py312\python.exe' (Join-Path $PSScriptRoot 'run-service.py') learning-worker

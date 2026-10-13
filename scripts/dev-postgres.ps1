# 文件说明：显式选择隔离PostgreSQL环境启动服务，不覆盖旧.env及旧业务目录。
param(
    [ValidateSet('api', 'worker', 'learning-worker')]
    [string]$Service = 'api',
    [switch]$Once
)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$env:PLATFORM_ENV_FILE = Join-Path $projectRoot 'var\postgres-dev\platform.env'
if (-not (Test-Path -LiteralPath $env:PLATFORM_ENV_FILE)) { throw '请先配置PostgreSQL隔离环境' }
$env:PYTHONIOENCODING = 'utf-8'
$OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$serviceArgs = @($Service)
if ($Once) {
    if ($Service -eq 'api') { throw 'API不支持Once' }
    $serviceArgs += '--once'
}
& 'D:\3-anaconda\envs\py312\python.exe' (Join-Path $PSScriptRoot 'run-service.py') @serviceArgs
exit $LASTEXITCODE

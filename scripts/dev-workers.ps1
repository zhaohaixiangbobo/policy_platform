# 文件说明：一次启动两个相互独立的后台Worker。
# 入库Worker负责解析、分块、索引和发布；学习Worker负责学习检测题目生成。
# 两者保持独立进程，便于分别停止、记录日志和避免模型生成阻塞入库流水线。
$ErrorActionPreference = 'Stop'
$pythonPath = 'D:\3-anaconda\envs\py312\python.exe'
if (-not (Test-Path -LiteralPath $pythonPath)) {
    throw "固定Python解释器不存在：$pythonPath"
}
# 监督器负责真实PID、功能开关、角色互斥和协作式停止。
& $pythonPath (Join-Path $PSScriptRoot 'run-service.py') workers
if ($LASTEXITCODE -ne 0) {
    throw "Worker监督器退出，退出码：$LASTEXITCODE；请检查上方日志。"
}

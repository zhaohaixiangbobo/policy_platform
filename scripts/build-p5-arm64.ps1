# 文件说明：专用BuildKit预检、独立小验证及四镜像导出；不加载交付镜像，不清理缓存。
# 默认联网做manifest预检；仅显式-ReuseVerifiedManifest <运行编号或目录>时复用历史成功记录，
# 复用前在本地按内容摘要严格校验，无法证明即报错，要求重新联网预检。
# 下载源参数（-AptMirror/-AptSecurityMirror/-LibreOfficeBaseUrl/-PipIndexUrl）仅用于-BuildAndExport，默认全部官方源；
# 只更换下载来源，基础镜像摘要、LibreOffice版本与SHA256保持不变，实际使用的源写入交付目录。
# -ReuseBackendFrom <运行编号>仅用于-BuildAndExport：经p5-verify-backend-tar.py严格校验后复用该轮backend.tar，不再构建后端。
# 构建器内嵌的buildkitd配置须与deploy/buildkit-p5.toml一致；修改该文件后须重建构建器，本脚本只检查不重建。
[CmdletBinding()]
param(
    [switch]$BuildAndExport,
    [ValidatePattern('^$|^[a-zA-Z0-9.-]+(:[0-9]+)?$')][string]$ManifestRegistry = '',
    [ValidateSet('None','Export','Arm64')][string]$Probe = 'None',
    [string]$ReuseVerifiedManifest = '',
    [ValidateSet('official','tuna')][string]$AptMirror = 'official',
    [ValidateSet('official','tuna')][string]$AptSecurityMirror = 'official',
    [string]$LibreOfficeBaseUrl = '',
    [string]$PipIndexUrl = '',
    [ValidatePattern('^$|^\d{8}-\d{6}-[a-f0-9]{8}$')][string]$ReuseBackendFrom = '',
    [string]$PythonExe = 'D:\3-anaconda\envs\py312\python.exe'
)
$ErrorActionPreference = 'Stop'
Set-Location (Split-Path $PSScriptRoot -Parent)
if ($BuildAndExport -and $Probe -ne 'None') { throw '正式构建与小验证分别执行' }
if ($ReuseVerifiedManifest) {
    if ($ManifestRegistry) { throw '-ReuseVerifiedManifest不联网，不能同时指定-ManifestRegistry' }
    if ($Probe -eq 'Export') { throw 'Export探针不做manifest预检，无需-ReuseVerifiedManifest' }
    if (-not $BuildAndExport -and $Probe -ne 'Arm64') { throw '-ReuseVerifiedManifest仅用于-BuildAndExport或-Probe Arm64；单独预检请联网执行' }
}
if (-not $BuildAndExport -and ($AptMirror -ne 'official' -or $AptSecurityMirror -ne 'official' -or $LibreOfficeBaseUrl -or $PipIndexUrl)) {
    throw '下载源参数仅用于-BuildAndExport'
}
if ($ReuseBackendFrom) {
    if (-not $BuildAndExport) { throw '-ReuseBackendFrom仅用于-BuildAndExport' }
    # 复用时下载源以来源轮次的build-sources.json为准，再指定会造成记录与实际镜像不符。
    if ($AptMirror -ne 'official' -or $AptSecurityMirror -ne 'official' -or $LibreOfficeBaseUrl -or $PipIndexUrl) {
        throw '-ReuseBackendFrom不构建后端，不能同时指定下载源参数；实际下载源以来源轮次记录为准'
    }
    if (-not (Test-Path -LiteralPath $PythonExe -PathType Leaf)) { throw "未找到Python解释器：$PythonExe；请用-PythonExe指定" }
}
. (Join-Path $PSScriptRoot 'p5-manifest-reuse.ps1')
. (Join-Path $PSScriptRoot 'p5-build-sources.ps1')
# 创建交付目录前完成源参数校验，并确认Dockerfile确实声明和使用这些参数。
$sources = Get-P5BuildSources -AptMirror $AptMirror -AptSecurityMirror $AptSecurityMirror -LibreOfficeBaseUrl $LibreOfficeBaseUrl -PipIndexUrl $PipIndexUrl
$builder = 'policy-p5-arm64'
$lock = Get-Content deploy/p5-images.json -Raw -Encoding UTF8 | ConvertFrom-Json
$runId = (Get-Date -Format 'yyyyMMdd-HHmmss') + '-' + [guid]::NewGuid().ToString('N').Substring(0,8)
$dest = Join-Path 'var/p5-delivery' $runId
New-Item -ItemType Directory -Path $dest | Out-Null
Copy-Item deploy/p5-images.json "$dest/source-lock.json"
Copy-Item deploy/buildkit-p5.toml "$dest/buildkit-p5.toml"
Write-Host "本轮记录：$dest"

function Invoke-LoggedCommand {
    param([string]$Name, [string]$Exe, [string[]]$Arguments)
    # PS5.1原生stderr可能包装为ErrorRecord；实时保留plain日志，最终按退出码判断。
    # 空stderr行包装后字符串化为RemoteException类型名，取Exception.Message保留原文。
    # docker/python输出UTF-8，控制台默认代码页936会把中文误解码并吞掉行尾字符，调用期间临时切到UTF-8。
    $saved = $ErrorActionPreference
    $savedEncoding = [Console]::OutputEncoding
    $savedPythonEncoding = $env:PYTHONIOENCODING
    try {
        $ErrorActionPreference = 'Continue'
        [Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)
        $env:PYTHONIOENCODING = 'utf-8'
        & $Exe @Arguments 2>&1 | ForEach-Object {
            $line = if ($_ -is [System.Management.Automation.ErrorRecord]) { $_.Exception.Message } else { "$_" }
            Add-Content -LiteralPath "$dest/$Name.log" -Value $line -Encoding UTF8
            Write-Host $line
        }
        $code = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $saved
        [Console]::OutputEncoding = $savedEncoding
        $env:PYTHONIOENCODING = $savedPythonEncoding
    }
    if ($code -ne 0) { throw "$Name 失败：$code；日志和缓存保留" }
}
function Invoke-LoggedDocker {
    param([string]$Name, [string[]]$Arguments)
    Invoke-LoggedCommand $Name 'docker' $Arguments
}
function Get-BuildkitSettings([string]$Text) {
    # 只比对影响本流程的设置：docker.io镜像站顺序、gc与并发；buildx会重新序列化TOML，故不做逐字比较。
    $body = (($Text -split "`r?`n") | Where-Object { $_.Trim() -notlike '#*' }) -join "`n"
    $mirrors = [regex]::Match($body, '(?s)\[registry\."docker\.io"\][^\[]*?mirrors\s*=\s*\[([^\]]*)\]')
    $hosts = if ($mirrors.Success) { @([regex]::Matches($mirrors.Groups[1].Value, '"([^"]*)"') | ForEach-Object { $_.Groups[1].Value }) } else { @() }
    $gc = [regex]::Match($body, '(?m)^\s*gc\s*=\s*(\w+)').Groups[1].Value
    $parallel = [regex]::Match($body, '(?m)^\s*max-parallelism\s*=\s*(\d+)').Groups[1].Value
    return "mirrors=$($hosts -join ',');gc=$gc;max-parallelism=$parallel"
}
function Confirm-BuildkitConfig($Node) {
    $encoded = if ($Node.Files) { $Node.Files.'buildkitd.toml' } else { $null }
    if (-not $encoded) { throw "构建器$builder 未内嵌buildkitd配置；请按P5_ARM64_DELIVERY.md用--buildkitd-config deploy/buildkit-p5.toml重建" }
    $effective = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($encoded))
    Set-Content "$dest/buildkitd-effective.toml" -Value $effective -Encoding UTF8
    $want = Get-BuildkitSettings (Get-Content deploy/buildkit-p5.toml -Raw -Encoding UTF8)
    $have = Get-BuildkitSettings $effective
    Write-Host "[buildkitd] 生效配置：$have"
    if ($want -ne $have) {
        throw "构建器生效配置（$have）与deploy/buildkit-p5.toml（$want）不一致：修改TOML不会自动生效，请按P5_ARM64_DELIVERY.md执行rm --keep-state后重新create"
    }
}
function Invoke-BackendReuse {
    # 先只读校验来源，再以.partial复制、摘要一致后改名；失败时本轮不留backend.tar。
    $full = (Resolve-Path -LiteralPath $dest).Path
    Invoke-LoggedCommand 'backend-reuse' $PythonExe @('scripts/p5-verify-backend-tar.py','--source',$ReuseBackendFrom,'--dest',$full,'--builder',$builder)
    $report = Get-Content "$dest/backend-reuse.json" -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($report.result -ne 'PASS' -or -not (Test-Path "$dest/backend.tar")) { throw '后端复用校验未通过；未构建后端，请查看backend-reuse.json' }
    return $report
}
function Get-QueryReference([string]$Reference) {
    if (-not $ManifestRegistry) { return $Reference }
    $parts = $Reference -split '@',2
    if ($parts.Count -ne 2 -or $parts[1] -notmatch '^sha256:[a-f0-9]{64}$') { throw '摘要格式不合法' }
    $repo = $parts[0] -replace ':[^/]+$',''
    if (-not $repo.Contains('/')) { $repo = 'library/' + $repo }
    return "$ManifestRegistry/$repo@$($parts[1])"
}
function Invoke-ManifestChecks {
    $evidence = @()
    foreach ($item in $lock.sources.PSObject.Properties) {
        $query = Get-QueryReference $item.Value
        Write-Host "[manifest] $query"
        $saved = $ErrorActionPreference
        try {
            $ErrorActionPreference = 'Continue'
            $raw = & docker buildx --builder $builder imagetools inspect --raw $query 2> "$dest/$($item.Name)-manifest.stderr.log"
            $code = $LASTEXITCODE
        } finally { $ErrorActionPreference = $saved }
        # PowerShell 5.1原生重定向默认UTF-16，统一转换为UTF-8日志。
        $errorLog = "$dest/$($item.Name)-manifest.stderr.log"
        if (Test-Path $errorLog) {
            $errorText = Get-Content $errorLog -Raw
            Set-Content $errorLog -Value $errorText -Encoding UTF8
        }
        if ($code -ne 0) { throw 'manifest失败；不自动换摘要或跳过检查' }
        $raw | Set-Content "$dest/$($item.Name)-manifest.json" -Encoding UTF8
        $manifest = ($raw -join "`n") | ConvertFrom-Json
        $arm = @($manifest.manifests | Where-Object { $_.platform.os -eq 'linux' -and $_.platform.architecture -eq 'arm64' })
        if ($arm.Count -eq 0) { throw "$($item.Name)缺少ARM64子清单" }
        foreach ($entry in $arm) { if ($entry.digest -notmatch '^sha256:[a-f0-9]{64}$') { throw 'ARM64摘要格式错误' } }
        $evidence += [pscustomobject]@{image=$item.Name;original_reference=$item.Value;query_reference=$query;checked_at_utc=[DateTime]::UtcNow.ToString('o');arm64=$arm}
        $evidence | ConvertTo-Json -Depth 20 | Set-Content "$dest/manifest-evidence.json" -Encoding UTF8
    }
}
function Invoke-ManifestReuse {
    # 复用历史联网预检：校验通过后把来源、时间、结果和所用文件副本写入本轮目录，便于追溯。
    try {
        $report = Confirm-VerifiedManifestRecord -Source $ReuseVerifiedManifest -DeliveryRoot 'var/p5-delivery' -LockPath 'deploy/p5-images.json' -Builder $builder
    } catch {
        throw "历史manifest记录无法可靠验证，请去掉-ReuseVerifiedManifest重新联网预检：$($_.Exception.Message)"
    }
    $copy = Join-Path $dest 'reused-manifest'
    New-Item -ItemType Directory -Path $copy | Out-Null
    foreach ($file in @($report.files)) { Copy-Item -LiteralPath (Join-Path $report.source_full_path $file.name) -Destination $copy }
    $report | ConvertTo-Json -Depth 20 | Set-Content "$dest/manifest-reuse.json" -Encoding UTF8
    Write-Host "[manifest] 复用$($report.source_run)（完成于$($report.source_completed_at_utc)）：五个镜像索引摘要与ARM64子清单本地校验通过"
    return $report
}
function Export-Image {
    param([string]$Name,[string]$Dockerfile,[string]$Context,[string[]]$BuildArgs)
    $command = @('buildx','--builder',$builder,'build','--platform','linux/arm64','--progress','plain','--provenance=false','--metadata-file',"$dest/$Name-metadata.json",'-f',$Dockerfile,'-t',$lock.outputs.$Name,'--output',"type=docker,dest=$dest/$Name.tar")
    Invoke-LoggedDocker "$Name-build" ($command + $BuildArgs + @($Context))
}
function Get-BuilderInfo {
    # Buildx v0.23不支持inspect --format；改用ls --format json（每行一个构建器），只读查询，不bootstrap。
    $errorLog = "$dest/builder.stderr.log"
    $saved = $ErrorActionPreference
    try {
        $ErrorActionPreference = 'Continue'
        $lines = & docker buildx ls --format json 2> $errorLog
        $code = $LASTEXITCODE
    } finally { $ErrorActionPreference = $saved }
    if (Test-Path $errorLog) { Set-Content $errorLog -Value (Get-Content $errorLog -Raw) -Encoding UTF8 }
    if ($code -ne 0) { throw "docker buildx ls执行失败（退出码$code），请确认Docker Desktop运行正常；详见builder.stderr.log" }
    $found = @()
    foreach ($line in @($lines)) {
        $text = "$line".Trim()
        if (-not $text) { continue }
        try { $item = $text | ConvertFrom-Json } catch { throw "buildx ls输出不是预期JSON，可能为Buildx版本格式变化：$text" }
        if ($item.Name -eq $builder) { $found += $item }
    }
    if ($found.Count -eq 0) { throw "未找到专用构建器$builder；请由用户按手册创建，本脚本不创建构建器" }
    if ($found.Count -gt 1) { throw "构建器$builder 出现多条记录，请人工核对" }
    return $found[0]
}
# 只检查既有builder，不bootstrap，不创建或下载；三类失败分别提示。
$info = Get-BuilderInfo
$info | ConvertTo-Json -Depth 20 | Set-Content "$dest/builder.json" -Encoding UTF8
if ($info.Driver -ne 'docker-container') { throw "构建器驱动为$($info.Driver)，必须为docker-container" }
$nodes = @($info.Nodes)
if ($nodes.Count -ne 1) { throw "构建器应为单节点，实际$($nodes.Count)个；请人工核对" }
$node = $nodes[0]
if ($node.Status -eq 'running') {
    # 平台列表仅在节点运行时可得。
    if (@($node.Platforms) -notcontains 'linux/arm64') { throw "构建器节点不支持linux/arm64（实际：$(@($node.Platforms) -join ',')）；请检查QEMU/binfmt" }
}
if ($BuildAndExport -or $Probe -ne 'None') {
    if ($node.Status -ne 'running') { throw "构建器节点状态为$($node.Status)，需运行中；请手动bootstrap后重试" }
    if ($node.Version -ne 'v0.21.0') { throw "BuildKit版本为$($node.Version)，需要v0.21.0；请人工核对" }
    Confirm-BuildkitConfig $node
}
if ($Probe -eq 'Export') {
    Invoke-LoggedDocker 'probe-export' @('buildx','--builder',$builder,'build','--platform','linux/arm64','--progress','plain','--provenance=false','-f','backend/tests/p5_build/Export.Dockerfile','-t','policy-platform/p5-export-probe:local','--output',"type=docker,dest=$dest/export-probe.tar",'backend/tests/p5_build')
    $raw = & tar -xOf "$dest/export-probe.tar" manifest.json
    if ($LASTEXITCODE -ne 0) { throw '归档缺少Docker manifest.json' }
    $entries = @(($raw -join "`n") | ConvertFrom-Json)
    $raw = & tar -xOf "$dest/export-probe.tar" $entries[0].Config
    if ($LASTEXITCODE -ne 0) { throw '归档缺少镜像配置' }
    $config = ($raw -join "`n") | ConvertFrom-Json
    if ($config.architecture -ne 'arm64' -or $config.os -ne 'linux') { throw '归档架构错误' }
    'PASS: Docker archive linux/arm64; no image loaded' | Set-Content "$dest/probe-result.txt" -Encoding UTF8
} else {
    if ($ReuseVerifiedManifest) { $reuse = Invoke-ManifestReuse } else { Invoke-ManifestChecks }
    if ($Probe -eq 'Arm64') {
        # no-cache仅强制小探针的RUN实际执行，不删除已存在缓存。
        Invoke-LoggedDocker 'probe-arm64' @('buildx','--builder',$builder,'build','--platform','linux/arm64','--progress','plain','--no-cache','--build-arg',"BASE_IMAGE=$($lock.sources.python)",'-f','backend/tests/p5_build/Arm64.Dockerfile','--output',"type=local,dest=$dest/arm64-result",'backend/tests/p5_build')
        if ((Get-Content "$dest/arm64-result/probe.txt" -Raw -Encoding UTF8).Trim() -ne 'aarch64 64') { throw 'ARM64执行结果错误' }
        'PASS: ARM64 RUN executed; not UOS page-size acceptance' | Set-Content "$dest/probe-result.txt" -Encoding UTF8
    } elseif ($BuildAndExport) {
        Write-Host '预计20至60分钟或更久；正式构建复用缓存，逐阶段保存日志。'
        if ($ReuseBackendFrom) {
            # build-sources.json由校验器从来源轮次复制，记录的是后端镜像实际使用的下载源。
            $backendReuse = Invoke-BackendReuse
        } else {
            # 实际下载源写入元数据与后端构建日志开头；Dockerfile内的[apt-sources]/[libreoffice]/[pip]输出可与之对照。
            $sources.record | ConvertTo-Json -Depth 5 | Set-Content "$dest/build-sources.json" -Encoding UTF8
            foreach ($property in $sources.record.PSObject.Properties) {
                $line = "[sources] $($property.Name)=$($property.Value)"
                Add-Content -LiteralPath "$dest/backend-build.log" -Value $line -Encoding UTF8
                Write-Host $line
            }
            Export-Image 'backend' 'deploy/Dockerfile.backend' '.' (@('--build-arg',"PYTHON_IMAGE=$($lock.sources.python)") + $sources.build_args)
        }
        Export-Image 'web' 'deploy/Dockerfile.web' '.' @('--build-arg',"NODE_IMAGE=$($lock.sources.node)",'--build-arg',"NGINX_IMAGE=$($lock.sources.nginx)")
        foreach ($name in @('postgres','qdrant')) {
            Export-Image $name 'deploy/Dockerfile.image-export' 'backend/tests/p5_build' @('--build-arg',"BASE_IMAGE=$($lock.sources.$name)")
        }
        Get-ChildItem $dest -Filter *.tar | Get-FileHash -Algorithm SHA256 |
            Select-Object Hash,@{Name='File';Expression={Split-Path $_.Path -Leaf}} |
            ConvertTo-Json | Set-Content "$dest/checksums.json" -Encoding UTF8
    }
}
$manifestMode = if ($Probe -eq 'Export') { 'none' } elseif ($ReuseVerifiedManifest) { 'reused' } else { 'online' }
$manifestSource = if ($ReuseVerifiedManifest) { $reuse.source_run } else { $null }
$buildSources = if ($ReuseBackendFrom) { Get-Content "$dest/build-sources.json" -Raw -Encoding UTF8 | ConvertFrom-Json } elseif ($BuildAndExport) { $sources.record } else { $null }
$backendMode = if (-not $BuildAndExport) { $null } elseif ($ReuseBackendFrom) { 'reused' } else { 'built' }
$backendSource = if ($ReuseBackendFrom) { $backendReuse.source_run } else { $null }
[pscustomobject]@{completed_at_utc=[DateTime]::UtcNow.ToString('o');builder=$builder;probe=$Probe;build=[bool]$BuildAndExport;manifest_mode=$manifestMode;manifest_source=$manifestSource;backend_mode=$backendMode;backend_source=$backendSource;build_sources=$buildSources} |
    ConvertTo-Json -Depth 5 | Set-Content "$dest/completed.json" -Encoding UTF8
Write-Host "完成：$dest；没有加载交付镜像或清理缓存。"

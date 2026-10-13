# 文件说明：P5历史manifest验证记录的本地严格校验；只读文件，不访问网络或Docker。
# 由build-p5-arm64.ps1在显式-ReuseVerifiedManifest时加载；任何一项无法证明即抛出带错误码的异常。
# 错误码前缀固定为英文，供静态测试断言：
#   REUSE-SOURCE / REUSE-NOT-SUCCESS / REUSE-INCOMPLETE / REUSE-LOCK-MISMATCH
#   REUSE-PLATFORM / REUSE-EVIDENCE / REUSE-DIGEST-MISMATCH / REUSE-ARM64-MISMATCH

$script:P5RequiredImages = @('python', 'node', 'nginx', 'postgres', 'qdrant')
$script:P5RunIdPattern = '^\d{8}-\d{6}-[0-9a-f]{8}$'

function Get-P5Sha256Hex([byte[]]$Bytes) {
    $sha = [Security.Cryptography.SHA256]::Create()
    try { $hash = $sha.ComputeHash($Bytes) } finally { $sha.Dispose() }
    return (($hash | ForEach-Object { $_.ToString('x2') }) -join '')
}

function Resolve-P5FullPath([string]$Path) {
    # .NET文件API按进程工作目录解析相对路径，与PowerShell的Set-Location不同步；统一转为绝对路径。
    return (Resolve-Path -LiteralPath $Path -ErrorAction Stop).ProviderPath
}

function Read-P5Utf8Text([string]$Path) {
    # 兼容带BOM/不带BOM的UTF-8；去掉BOM后返回原文。
    $text = [IO.File]::ReadAllText((Resolve-P5FullPath $Path), [Text.UTF8Encoding]::new($false))
    if ($text.Length -gt 0 -and $text[0] -eq [char]0xFEFF) { $text = $text.Substring(1) }
    return $text
}

function Get-P5ManifestDigest([string]$Path) {
    # 在线预检按行捕获原始manifest并以UTF-8 BOM+CRLF保存；还原为LF、去掉末尾换行后，
    # 其sha256即镜像索引摘要。还原失败时摘要必然不一致，按不可信处理。
    $text = (Read-P5Utf8Text $Path).TrimEnd("`r", "`n") -replace "`r`n", "`n"
    return 'sha256:' + (Get-P5Sha256Hex ([Text.UTF8Encoding]::new($false).GetBytes($text)))
}

function ConvertTo-P5UtcDate($Value, [string]$Field) {
    # PS5.1的ConvertFrom-Json保留字符串，PS7会转成DateTime；两者统一为UTC时间。
    if ($Value -is [datetime]) { return $Value.ToUniversalTime() }
    $parsed = [datetime]::MinValue
    $ok = [datetime]::TryParse([string]$Value, [Globalization.CultureInfo]::InvariantCulture,
        [Globalization.DateTimeStyles]::RoundtripKind, [ref]$parsed)
    if (-not $ok) { throw "[REUSE-EVIDENCE] $Field 不是有效时间：$Value" }
    return $parsed.ToUniversalTime()
}

function Read-P5JsonFile([string]$Path, [string]$Code) {
    try { $text = Read-P5Utf8Text $Path }
    catch { throw "[$Code] 无法读取$(Split-Path $Path -Leaf)：$($_.Exception.Message)" }
    try { return ($text | ConvertFrom-Json) }
    catch { throw "[$Code] 无法解析JSON：$(Split-Path $Path -Leaf)：$($_.Exception.Message)" }
}

function Get-P5Arm64Entries($Manifest) {
    $entries = @()
    foreach ($entry in @($Manifest.manifests)) {
        if ($null -ne $entry -and $entry.platform.os -eq 'linux' -and $entry.platform.architecture -eq 'arm64') { $entries += $entry }
    }
    return , $entries
}

function Confirm-VerifiedManifestRecord {
    param(
        [Parameter(Mandatory)][string]$Source,
        [Parameter(Mandatory)][string]$DeliveryRoot,
        [Parameter(Mandatory)][string]$LockPath,
        [Parameter(Mandatory)][string]$Builder
    )
    $now = [DateTime]::UtcNow

    # 1. 来源目录：只能是交付根目录下的直接子目录，且名称符合本脚本生成的运行编号。
    if (-not (Test-Path -LiteralPath $DeliveryRoot -PathType Container)) { throw "[REUSE-SOURCE] 交付根目录不存在：$DeliveryRoot" }
    $rootFull = (Resolve-P5FullPath $DeliveryRoot).TrimEnd('\', '/')
    if (-not (Test-Path -LiteralPath $LockPath -PathType Leaf)) { throw "[REUSE-LOCK-MISMATCH] 当前锁文件不存在：$LockPath" }
    $LockPath = Resolve-P5FullPath $LockPath
    $candidate = if ($Source -match $script:P5RunIdPattern) { Join-Path $rootFull $Source } else { $Source }
    if (-not (Test-Path -LiteralPath $candidate -PathType Container)) { throw "[REUSE-SOURCE] 历史记录目录不存在：$Source" }
    $sourceFull = (Resolve-P5FullPath $candidate).TrimEnd('\', '/')
    $runName = Split-Path $sourceFull -Leaf
    if ((Split-Path $sourceFull -Parent).TrimEnd('\', '/') -ne $rootFull) { throw "[REUSE-SOURCE] 历史记录必须位于$DeliveryRoot 的直接子目录：$Source" }
    if ($runName -notmatch $script:P5RunIdPattern) { throw "[REUSE-SOURCE] 目录名不是本脚本生成的运行编号：$runName" }

    # 2. 必需文件齐全；缺completed.json视为未成功完成（失败目录不会写入该文件）。
    $completedPath = Join-Path $sourceFull 'completed.json'
    if (-not (Test-Path -LiteralPath $completedPath -PathType Leaf)) { throw "[REUSE-NOT-SUCCESS] 缺少completed.json，该目录不是成功完成的验证：$runName" }
    if (Test-Path -LiteralPath (Join-Path $sourceFull 'manifest-reuse.json')) { throw "[REUSE-NOT-SUCCESS] 该目录本身是复用记录，只接受联网预检的原始记录：$runName" }
    $required = @('source-lock.json', 'manifest-evidence.json')
    foreach ($name in $script:P5RequiredImages) { $required += "$name-manifest.json"; $required += "$name-manifest.stderr.log" }
    foreach ($file in $required) {
        if (-not (Test-Path -LiteralPath (Join-Path $sourceFull $file) -PathType Leaf)) { throw "[REUSE-INCOMPLETE] 缺少$file：$runName" }
    }

    # 3. completed.json：同一专用构建器、执行过在线manifest检查的模式。
    $completed = Read-P5JsonFile $completedPath 'REUSE-NOT-SUCCESS'
    if ($completed.builder -ne $Builder) { throw "[REUSE-NOT-SUCCESS] 构建器不一致：记录为$($completed.builder)，本次为$Builder" }
    if (@('None', 'Arm64') -notcontains [string]$completed.probe) { throw "[REUSE-NOT-SUCCESS] probe=$($completed.probe) 的运行不包含manifest预检" }
    if ($null -ne $completed.manifest_mode -and $completed.manifest_mode -ne 'online') { throw "[REUSE-NOT-SUCCESS] manifest_mode=$($completed.manifest_mode)，不是联网预检" }
    $completedAt = ConvertTo-P5UtcDate $completed.completed_at_utc 'completed_at_utc'
    if ($completedAt -gt $now.AddMinutes(5)) { throw "[REUSE-NOT-SUCCESS] completed_at_utc晚于当前时间：$($completed.completed_at_utc)" }

    # 4. 锁文件逐字节一致，且目标平台、镜像集合符合本次配置。
    $currentLockHash = (Get-FileHash -LiteralPath $LockPath -Algorithm SHA256).Hash.ToLowerInvariant()
    $sourceLockHash = (Get-FileHash -LiteralPath (Join-Path $sourceFull 'source-lock.json') -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($currentLockHash -ne $sourceLockHash) { throw "[REUSE-LOCK-MISMATCH] 历史记录的锁文件与当前deploy/p5-images.json不一致" }
    $lock = Read-P5JsonFile $LockPath 'REUSE-LOCK-MISMATCH'
    if ($lock.platform -ne 'linux/arm64') { throw "[REUSE-PLATFORM] 锁文件目标平台为$($lock.platform)，需要linux/arm64" }
    $lockNames = @($lock.sources.PSObject.Properties | ForEach-Object { $_.Name })
    if ((@($lockNames | Sort-Object) -join ',') -ne (@($script:P5RequiredImages | Sort-Object) -join ',')) { throw "[REUSE-LOCK-MISMATCH] 锁文件镜像集合应为$($script:P5RequiredImages -join ',')" }

    # 5. 证据记录：五个镜像各一条，引用与锁文件一致，检查时间不晚于完成时间。
    $evidenceRaw = Read-P5JsonFile (Join-Path $sourceFull 'manifest-evidence.json') 'REUSE-EVIDENCE'
    $evidence = @($evidenceRaw)
    $checkedNames = @($evidence | ForEach-Object { $_.image })
    if ((@($checkedNames | Sort-Object) -join ',') -ne (@($script:P5RequiredImages | Sort-Object) -join ',')) { throw "[REUSE-EVIDENCE] 证据应恰好包含五个镜像，实际：$($checkedNames -join ',')" }

    $images = @()
    $files = @()
    foreach ($name in $script:P5RequiredImages) {
        $reference = [string]$lock.sources.$name
        $parts = $reference -split '@', 2
        if ($parts.Count -ne 2 -or $parts[1] -notmatch '^sha256:[a-f0-9]{64}$') { throw "[REUSE-LOCK-MISMATCH] $name 锁定引用缺少完整sha256：$reference" }
        $digest = $parts[1]
        $item = @($evidence | Where-Object { $_.image -eq $name })[0]
        if ($item.original_reference -ne $reference) { throw "[REUSE-EVIDENCE] $name 原始引用不一致：$($item.original_reference)" }
        if (-not ([string]$item.query_reference).EndsWith("@$digest")) { throw "[REUSE-EVIDENCE] $name 查询引用未使用锁定摘要：$($item.query_reference)" }
        $checkedAt = ConvertTo-P5UtcDate $item.checked_at_utc "$name.checked_at_utc"
        if ($checkedAt -gt $completedAt) { throw "[REUSE-EVIDENCE] $name 检查时间晚于运行完成时间" }

        # 6. 失败痕迹：stderr日志必须为空。
        $stderrPath = Join-Path $sourceFull "$name-manifest.stderr.log"
        if (-not [string]::IsNullOrWhiteSpace((Read-P5Utf8Text $stderrPath))) { throw "[REUSE-NOT-SUCCESS] $name 的manifest查询留有错误输出" }

        # 7. 原始manifest按内容寻址：还原字节的sha256必须等于锁定摘要。
        $manifestPath = Join-Path $sourceFull "$name-manifest.json"
        $actual = Get-P5ManifestDigest $manifestPath
        if ($actual -ne $digest) { throw "[REUSE-DIGEST-MISMATCH] $name 历史manifest摘要为$actual，锁定为$digest" }
        $manifest = Read-P5JsonFile $manifestPath 'REUSE-DIGEST-MISMATCH'

        # 8. ARM64子清单：从已证实的原始manifest重新提取，并与证据逐项比对。
        $fromManifest = Get-P5Arm64Entries $manifest
        $fromEvidence = @($item.arm64)
        if ($fromManifest.Count -eq 0) { throw "[REUSE-ARM64-MISMATCH] $name 原始manifest不含linux/arm64子清单" }
        if ($fromManifest.Count -ne $fromEvidence.Count) { throw "[REUSE-ARM64-MISMATCH] $name ARM64子清单数量不一致" }
        $armRecords = @()
        for ($i = 0; $i -lt $fromManifest.Count; $i++) {
            $m = $fromManifest[$i]; $e = $fromEvidence[$i]
            if ($m.digest -notmatch '^sha256:[a-f0-9]{64}$') { throw "[REUSE-ARM64-MISMATCH] $name ARM64摘要格式错误" }
            $same = ($m.digest -eq $e.digest) -and ("$($m.size)" -eq "$($e.size)") -and
                ($e.platform.os -eq 'linux') -and ($e.platform.architecture -eq 'arm64') -and
                ("$($m.platform.variant)" -eq "$($e.platform.variant)")
            if (-not $same) { throw "[REUSE-ARM64-MISMATCH] $name 证据中的ARM64子清单与原始manifest不一致：$($e.digest)" }
            $armRecords += [pscustomobject]@{ digest = $m.digest; size = $m.size; platform = "linux/arm64$(if ($m.platform.variant) { '/' + $m.platform.variant })" }
        }
        $images += [pscustomobject]@{
            image = $name; original_reference = $reference; index_digest = $digest
            manifest_sha256_recomputed = $actual; source_checked_at_utc = $checkedAt.ToString('o'); arm64 = $armRecords
        }
    }

    # 9. 记录所用文件的哈希，复制后可再核对。
    foreach ($file in @('completed.json') + $required) {
        $files += [pscustomobject]@{ name = $file; sha256 = (Get-FileHash -LiteralPath (Join-Path $sourceFull $file) -Algorithm SHA256).Hash.ToLowerInvariant() }
    }
    return [pscustomobject]@{
        result = 'PASS'
        verified_at_utc = $now.ToString('o')
        source_run = $runName
        source_full_path = $sourceFull
        source_completed_at_utc = $completedAt.ToString('o')
        source_probe = [string]$completed.probe
        builder = $Builder
        platform = $lock.platform
        lock_sha256 = $currentLockHash
        images = $images
        files = $files
    }
}

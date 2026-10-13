# 文件说明：P5正式构建的下载源选择；把脚本参数映射为Dockerfile.backend构建参数，并生成可追溯记录。
# 只做本地映射与校验，不访问网络；默认全部官方源，与P4本地构建一致。
# Debian主仓库与security仓库分别选择；LibreOffice版本与SHA256固定在Dockerfile中，此处只换下载来源。

$script:P5AptPresets = @{
    official = @{ debian = ''; security = '' }
    tuna     = @{ debian = 'https://mirrors.tuna.tsinghua.edu.cn/debian'; security = 'https://mirrors.tuna.tsinghua.edu.cn/debian-security' }
}
$script:P5OfficialSources = @{
    debian      = 'http://deb.debian.org/debian'
    security    = 'http://deb.debian.org/debian-security'
    libreoffice = 'https://downloadarchive.documentfoundation.org/libreoffice/old'
    pypi        = 'https://pypi.org/simple'
}
$script:P5HttpsUrlPattern = '^https://[A-Za-z0-9.-]+(:[0-9]+)?(/[A-Za-z0-9._~/-]*)?$'
$script:P5SourceBuildArgs = @('DEBIAN_MIRROR', 'DEBIAN_SECURITY_MIRROR', 'LIBREOFFICE_BASE_URL', 'PYPI_INDEX_URL')

function Get-P5BuildSources {
    param(
        [ValidateSet('official', 'tuna')][string]$AptMirror = 'official',
        [ValidateSet('official', 'tuna')][string]$AptSecurityMirror = 'official',
        [string]$LibreOfficeBaseUrl = '',
        [string]$PipIndexUrl = '',
        [string]$DockerfilePath = 'deploy/Dockerfile.backend',
        [string]$AptSourcesPath = 'deploy/apt-sources.sh'
    )
    foreach ($pair in @(@('LibreOfficeBaseUrl', $LibreOfficeBaseUrl), @('PipIndexUrl', $PipIndexUrl))) {
        if ($pair[1] -and $pair[1] -cnotmatch $script:P5HttpsUrlPattern) { throw "-$($pair[0])必须是https地址且不含空格、引号等字符：$($pair[1])" }
    }

    # Dockerfile必须在最终阶段（最后一个FROM之后）声明并在声明之后使用每个源参数；
    # FROM之前的ARG对RUN不可见，未声明的参数docker只给警告，均会被静默丢弃。
    # Debian两个参数由apt-sources.sh从环境变量读取，须在调用该脚本的RUN之前声明；
    # 并且必须以"${NAME:-}"形式作为替换参数使用，仅出现在日志输出中不算生效。
    $dockerfile = Get-Content -LiteralPath $DockerfilePath -Raw -Encoding UTF8
    $aptSources = Get-Content -LiteralPath $AptSourcesPath -Raw -Encoding UTF8
    $froms = [regex]::Matches($dockerfile, '(?m)^FROM ')
    if ($froms.Count -eq 0) { throw "$DockerfilePath 缺少FROM" }
    $stage = $dockerfile.Substring($froms[$froms.Count - 1].Index)
    foreach ($name in $script:P5SourceBuildArgs) {
        $declared = [regex]::Match($stage, "(?m)^ARG $name=")
        if (-not $declared.Success) { throw "$DockerfilePath 未声明ARG $name，下载源参数不会生效" }
        $after = $stage.Substring($declared.Index + $declared.Length)
        $used = if ($name -like 'DEBIAN_*') {
            $after.Contains('sh /tmp/apt-sources.sh apply') -and $aptSources.Contains('"${' + $name + ':-}"')
        } else {
            $after.Contains('$' + $name) -or $after.Contains('${' + $name)
        }
        if (-not $used) { throw "$DockerfilePath 声明后未使用$name，下载源参数不会生效" }
    }
    $armSum = [regex]::Match($dockerfile, 'arm64\) dir=aarch64; pkg=aarch64; sum=([a-f0-9]{64})').Groups[1].Value
    $version = [regex]::Match($dockerfile, 'version=([0-9.]+);').Groups[1].Value
    if (-not $armSum -or -not $version) { throw "$DockerfilePath 未找到固定的LibreOffice版本或ARM64 SHA256" }

    $debian = $script:P5AptPresets[$AptMirror].debian
    $security = $script:P5AptPresets[$AptSecurityMirror].security
    $buildArgs = @(
        '--build-arg', "DEBIAN_MIRROR=$debian",
        '--build-arg', "DEBIAN_SECURITY_MIRROR=$security",
        '--build-arg', "LIBREOFFICE_BASE_URL=$LibreOfficeBaseUrl",
        '--build-arg', "PYPI_INDEX_URL=$PipIndexUrl"
    )
    $record = [pscustomobject][ordered]@{
        apt_mirror               = $AptMirror
        debian_uri               = $(if ($debian) { $debian } else { $script:P5OfficialSources.debian })
        apt_security_mirror      = $AptSecurityMirror
        debian_security_uri      = $(if ($security) { $security } else { $script:P5OfficialSources.security })
        libreoffice_version      = $version
        libreoffice_base_url     = $(if ($LibreOfficeBaseUrl) { $LibreOfficeBaseUrl } else { $script:P5OfficialSources.libreoffice })
        libreoffice_arm64_sha256 = $armSum
        pypi_index_url           = $(if ($PipIndexUrl) { $PipIndexUrl } else { $script:P5OfficialSources.pypi })
        dockerfile_sha256        = (Get-FileHash -LiteralPath $DockerfilePath -Algorithm SHA256).Hash.ToLowerInvariant()
        # apt-sources.sh经RUN挂载使用、不在history中，登记摘要供后续复用backend.tar时核对。
        apt_sources_sha256       = (Get-FileHash -LiteralPath $AptSourcesPath -Algorithm SHA256).Hash.ToLowerInvariant()
    }
    return [pscustomobject]@{ build_args = $buildArgs; record = $record }
}

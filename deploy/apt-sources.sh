#!/bin/sh
# 文件说明：Debian 12 deb822源（debian.sources）的可选镜像切换，供Dockerfile.backend以bind挂载调用，不进入镜像。
# 用法：sh apt-sources.sh apply|restore
#   DEBIAN_MIRROR           主仓库（bookworm、bookworm-updates）地址；留空保持基础镜像官方源。
#   DEBIAN_SECURITY_MIRROR  security仓库地址；单独配置，留空保持官方源，不随主仓库一起替换。
# 只改URIs行，Signed-By与Suites不动，apt仍按Debian密钥校验签名与包哈希。
# 基础镜像源格式与预期不符时直接失败，不静默忽略镜像参数。
set -eu

file="${APT_SOURCES_FILE:-/etc/apt/sources.list.d/debian.sources}"
backup="$file.policy-orig"
official_main='http://deb.debian.org/debian'
official_security='http://deb.debian.org/debian-security'

fail() { echo "[apt-sources] $1" >&2; exit 1; }

# 只接受http/https地址，不允许空格、引号、#等会破坏sed或源文件的字符。
check_url() {
    printf '%s' "$1" | grep -Eq '^https?://[A-Za-z0-9.-]+(:[0-9]+)?(/[A-Za-z0-9._~/-]*)?$' || fail "镜像地址格式不合法：$1"
}

# 官方URIs行必须恰好一行，替换后再确认新行恰好一行。
replace_uri() {
    old="$1"; new="$2"; pattern="$3"
    [ -n "$new" ] || return 0
    check_url "$new"
    count=$(grep -cFx "URIs: $old" "$file" || true)
    [ "$count" = 1 ] || fail "期望恰好一行“URIs: $old”，实际$count行；基础镜像源格式变化，拒绝继续"
    sed -i "s#^URIs: $pattern\$#URIs: ${new%/}#" "$file"
    count=$(grep -cFx "URIs: ${new%/}" "$file" || true)
    [ "$count" = 1 ] || fail "替换后未找到“URIs: ${new%/}”"
}

case "${1:-}" in
    apply)
        [ -f "$file" ] || fail "源文件不存在：$file"
        cp "$file" "$backup"
        replace_uri "$official_main" "${DEBIAN_MIRROR:-}" 'http://deb\.debian\.org/debian'
        replace_uri "$official_security" "${DEBIAN_SECURITY_MIRROR:-}" 'http://deb\.debian\.org/debian-security'
        echo "[apt-sources] debian=${DEBIAN_MIRROR:-$official_main} security=${DEBIAN_SECURITY_MIRROR:-$official_security}"
        grep '^URIs:' "$file" | sed 's/^/[apt-sources] /'
        ;;
    restore)
        # 安装完成后恢复官方源配置，最终镜像不残留构建期镜像站地址。
        [ -f "$backup" ] || fail "缺少备份：$backup"
        mv "$backup" "$file"
        ;;
    *)
        fail "用法：apt-sources.sh apply|restore"
        ;;
esac

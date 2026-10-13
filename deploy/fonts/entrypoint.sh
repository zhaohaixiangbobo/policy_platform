#!/bin/sh
# 文件说明：以应用UID刷新外置字体缓存；原命令及业务参数原样执行。
set -eu
test -d /usr/local/share/fonts/policy
mkdir -p /tmp/policy-font-cache
fc-cache -f /usr/local/share/fonts/policy
exec "$@"

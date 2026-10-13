# 文件说明：测试Docker tar导出；不下载基础镜像，不执行ARM指令。
FROM scratch
COPY marker.txt /marker.txt

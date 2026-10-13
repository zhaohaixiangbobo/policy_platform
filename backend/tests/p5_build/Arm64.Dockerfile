# 文件说明：执行ARM64 Python，只输出探针文本，不加载镜像。
ARG BASE_IMAGE
FROM ${BASE_IMAGE} AS probe
RUN python -c "import platform,struct; m=platform.machine(); b=struct.calcsize('P')*8; assert m=='aarch64' and b==64,(m,b); open('/probe.txt','w').write(f'{m} {b}')"
FROM scratch
COPY --from=probe /probe.txt /probe.txt

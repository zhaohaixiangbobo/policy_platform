# P5 UOS 服务器环境基线

> 文件说明：记录生产目标机已核实环境及后续部署约束。状态 CURRENT，版本 uos_p5_baseline_v1，更新日期 2026-10-12。依据用户在服务器执行检查并提交的结果登记；Codex 本轮未远程复测或操作服务器。本记录不是业务部署验收通过证明。

## 1. 系统与存储

- 服务器：10.9.14.171，UOS Server 20（1070/fuyu/uel20），Linux ARM64。
- 内核：4.19.90-2403.3.0.0270.84.uel20.aarch64；内存页 65536 字节；宿主 glibc 2.28；cgroup v1；16 核、约 30GiB 内存。
- 系统盘 /dev/vda 80GB，根分区 XFS 70GB。
- 项目数据盘 /dev/vdb 500GB：/dev/vdb1 → data/data_lv，XFS，挂载 /data，ftype=1。
- findmnt --verify 通过，无错误或警告；已配置持久挂载。
- Docker Root Dir：/data/docker。
- Docker 管理的 containerd 持久化 root：/data/docker/containerd/daemon。
- containerd 运行时 state：/var/run/docker/containerd/daemon。
- containerd 由 dockerd 管理，无独立 containerd.service；无需迁移到 /data/containerd，也无需创建独立服务。

## 2. 已完成的启动保护

已创建并加载 /etc/systemd/system/docker.service.d/20-data-mount.conf：

```ini
[Unit]
RequiresMountsFor=/data/docker
ConditionPathIsMountPoint=/data
```

用户已执行 daemon-reload、重启和状态核验，Docker active，存储路径保持不变。挂载失败模拟尚未执行，不能宣称该故障场景已验收。

## 3. 组件基线

| 组件 | 当前版本 | 后续约束 |
|---|---|---|
| Docker Engine | 29.0.4 | 保留，不进行无必要升级或重装 |
| Docker API | 1.52 | 当前接口版本 |
| containerd | 2.1.5 | 保留，Docker 管理 |
| runc | 1.3.3 | 保留 |
| Docker Compose | v5.0.0-rc.2 | 暂时保留；正式部署前验证兼容性，必要时再换稳定正式版 |

Docker 使用 containerd snapshotter（overlayfs）；上述版本可运行 Docker 服务，不代表项目镜像已通过 ARM64 / 64KB 页兼容性验收。Docker、containerd、runc 安装来源尚未最终确认。

## 4. 后续 Compose 与交付约束

1. 以 /data 为持久化存储基础。PostgreSQL、Qdrant、上传文件等分别声明持久化卷映射，业务数据不依赖容器可写层、不进入镜像。
2. 可以保留独立命名卷，依托已确认的 Docker data-root 落在数据盘；最终部署配置应明确卷名、容器挂载路径和备份范围。不为改变目录外观扩大存储改造。
3. 镜像和部署配置适配 linux/arm64；实际目标机验证包含 64KB 内存页、资源限制、LibreOffice/字体和外部模型连通性。
4. 存储路径和挂载保护已经完成，后续不重复修改。运行时 state 留在 /run 或 /var/run。
5. 新环境为空白部署，不迁移旧业务数据；正式投入使用后，升级保留持久化数据。

## 5. 当前边界与下一阶段

2026-10-12 用户补充确认：UOS Server 20 1070e，10.9.14.171；Docker/containerd/runc二进制位于/usr/bin，rpm -qf确认不由RPM管理，可能为手动二进制部署，原包和来源仍未知。docker.service位于/etc/systemd/system/docker.service，挂载保护已加载，重启验证通过。

内网验收入口确定为http://10.9.14.171:80；尚待部署前实时核对端口占用。字体确定为/data/policy-platform/fonts，只读挂载，暂未上传。HTTPS及异机备份暂不建设，不作为ARM64交付准备前置条件，正式上线前再评估。Compose v5.0.0-rc.2保留并先验证兼容性。后续交付准备见[P5交付说明](P5_ARM64_DELIVERY.md)，本轮授权只包含本地配置与静态验证。

检查时无容器、无项目镜像导入、无 PostgreSQL 业务数据库初始化、无旧业务数据迁移。本轮仅登记基线，暂不执行项目部署、镜像导入、数据库初始化或数据迁移。

后续经用户安排推进：安装来源留档、Compose 兼容性验证、ARM64 镜像交付与实机测试、空库业务验收、成套备份与独立恢复演练。具体顺序仍服从现有 P0—P5 方案，不新增阶段或调度基础设施。

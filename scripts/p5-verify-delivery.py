"""文件说明：只读核验P5四镜像归档；可排他创建白名单配置包及校验报告，不调用Docker或服务器。"""
import argparse
import hashlib
import io
import json
from datetime import datetime, timezone
from pathlib import Path
import tarfile

ROOT = Path(__file__).resolve().parents[1]
NAMES = ('backend', 'web', 'postgres', 'qdrant')
CONFIG_FILES = (
    'compose.p5.yaml', 'deploy/compose.fonts.yaml', 'deploy/compose.operations.yaml',
    'deploy/nginx.conf', 'deploy/fonts/entrypoint.sh', 'deploy/fonts/99-policy-fonts.conf',
    'deploy/portal/portal-config.json', 'deploy/p5-images.json',
)


def read_json(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def checksum(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def verify(source):
    completed = read_json(source / 'completed.json')
    if completed.get('build') is not True or completed.get('probe') != 'None':
        raise ValueError('不是完成的正式构建轮次')
    lock = read_json(source / 'source-lock.json')
    if lock != read_json(ROOT / 'deploy/p5-images.json'):
        raise ValueError('交付锁文件与当前部署锁不同，先审查差异')
    checks = read_json(source / 'checksums.json')
    if len(checks) != 4 or {x['File'] for x in checks} != {n + '.tar' for n in NAMES}:
        raise ValueError('checksums.json必须准确包含四个镜像')
    expected = {x['File']: x['Hash'].lower() for x in checks}
    for mode in ('backend', 'manifest'):
        if completed.get(mode + '_mode') == 'reused':
            read_json(source / (mode + '-reuse.json'))
            if not (source / ('reused-' + mode)).is_dir():
                raise ValueError('复用证据目录缺失：' + mode)
    rows = []
    for name in NAMES:
        archive = source / (name + '.tar')
        digest = checksum(archive)
        if digest != expected[archive.name]:
            raise ValueError('文件SHA256不匹配：' + name)
        metadata = read_json(source / (name + '-metadata.json'))
        with tarfile.open(archive) as tar:
            manifests = json.load(tar.extractfile('manifest.json'))
            if len(manifests) != 1 or manifests[0]['RepoTags'] != [lock['outputs'][name]]:
                raise ValueError('镜像标签/数量不匹配：' + name)
            config_bytes = tar.extractfile(manifests[0]['Config']).read()
            config = json.loads(config_bytes)
            config_digest = 'sha256:' + hashlib.sha256(config_bytes).hexdigest()
            if config_digest != metadata['containerimage.config.digest']:
                raise ValueError('镜像配置摘要与metadata不一致：' + name)
            if (config.get('os'), config.get('architecture')) != ('linux', 'arm64'):
                raise ValueError('架构错误：' + name)
        rows.append(dict(name=name, file=archive.name, bytes=archive.stat().st_size,
                         sha256=digest, tag=lock['outputs'][name], platform='linux/arm64',
                         image_id=config_digest))
        print(f'PASS {name} bytes={archive.stat().st_size} sha256={digest}', flush=True)
    return dict(verified_at_utc=datetime.now(timezone.utc).isoformat(), source=str(source),
                result='ARCHIVE_VERIFIED_NOT_DEPLOYED', images=rows)


def prepare_upload(source, output, report):
    # 只打包不含凭据的部署配置；拒绝覆盖旧上传包，不复制任何业务数据。
    output.mkdir(parents=True, exist_ok=False)
    config_hashes = []
    with tarfile.open(output / 'deployment-config.tar', 'w') as tar:
        for name in CONFIG_FILES:
            data = (ROOT / name).read_text(encoding='utf-8-sig').replace('\r\n', '\n').encode('utf-8')
            info = tarfile.TarInfo(name)
            info.size, info.mode, info.mtime = len(data), 0o644, 0
            tar.addfile(info, io.BytesIO(data))
            config_hashes.append(hashlib.sha256(data).hexdigest() + '  ' + name)
        data = ('\n'.join(config_hashes) + '\n').encode('utf-8')
        info = tarfile.TarInfo('CONFIG_SHA256SUMS')
        info.size, info.mode = len(data), 0o644
        tar.addfile(info, io.BytesIO(data))
    (output / 'delivery-verification.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    lines = [r['sha256'] + '  ' + r['file'] for r in report['images']]
    for name in ('completed.json', 'checksums.json', 'source-lock.json'):
        lines.append(checksum(source / name) + '  ' + name)
    for name in ('deployment-config.tar', 'delivery-verification.json'):
        lines.append(checksum(output / name) + '  ' + name)
    (output / 'SHA256SUMS').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    print('上传辅助包：' + str(output))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--output', type=Path, help='可选：新目录保存校验报告和白名单配置包；不得已存在')
    args = parser.parse_args()
    if args.output and args.output.exists():
        raise ValueError('输出目录已存在，保留原包；只读重验请省略--output')
    source = args.source.resolve(strict=True)
    report = verify(source)
    if args.output:
        prepare_upload(source, args.output, report)


if __name__ == '__main__':
    main()

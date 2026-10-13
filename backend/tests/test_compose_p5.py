"""文件说明：P5交付配置静态检查；不连接Docker、模型或数据库。

manifest复用校验用例仅以powershell调用本地校验函数并读写临时目录，不访问网络或Docker。
下载源用例：apt-sources.sh以POSIX sh改写临时源文件；构建脚本以假docker在临时仓库副本中运行，
只记录实际传给docker的参数，不访问网络、不构建、不写入真实交付目录。
镜像站核验用例以假Registry离线运行；backend.tar复用用例在临时目录生成小型OCI归档。
本文件属于p5-verify-backend-tar.py的工具白名单；新增P5用例请写在这里，另建测试文件会使历史镜像与工作区不一致。
"""
import base64
import gzip
import hashlib
import io
import json
import tarfile
import tomllib
import os
import shutil
import subprocess
import sys
from pathlib import Path
import importlib.util

import pytest

ROOT = Path(__file__).resolve().parents[2]


def test_delivery_config_upload_whitelist():
    spec = importlib.util.spec_from_file_location('verify_delivery', ROOT / 'scripts/p5-verify-delivery.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert len(module.CONFIG_FILES) == 8
    assert all((ROOT / path).is_file() for path in module.CONFIG_FILES)
    assert all(not path.startswith('var/') and not path.endswith(('.env', '.ttf', '.ttc', '.sql'))
               for path in module.CONFIG_FILES)
    assert 'compose.p5.yaml' in module.CONFIG_FILES
    assert 'compose.yaml' not in module.CONFIG_FILES
POWERSHELL = shutil.which('powershell.exe') or shutil.which('pwsh')
REUSE_SCRIPT = ROOT / 'scripts/p5-manifest-reuse.ps1'
SOURCES_SCRIPT = ROOT / 'scripts/p5-build-sources.ps1'
BUILD_SCRIPT = ROOT / 'scripts/build-p5-arm64.ps1'
DOCKERFILE = ROOT / 'deploy/Dockerfile.backend'
APT_SOURCES = ROOT / 'deploy/apt-sources.sh'
# 以下固定值来自P4本地镜像p4-local的构建历史与deploy/p5-images.json，镜像源改造不得改变。
PYTHON_IMAGE = 'python:3.12-slim-bookworm@sha256:34386ef0cb081344d7ec1c103ba398e6e9f64e9ab3a1509accc92a4e24a07258'
LIBREOFFICE_VERSION = '26.8.1.1'
LIBREOFFICE_SUMS = {
    'amd64': '30903df3b9f61360d9660cd707de48cd2831469114492a5008ed58a0ac77d044',
    'arm64': '1b069c20dd237f6decad3ea02cb02f39fdf458b03d09c2a9facb7b9b71e6a27a',
}
TUNA_DEBIAN = 'https://mirrors.tuna.tsinghua.edu.cn/debian'
TUNA_SECURITY = 'https://mirrors.tuna.tsinghua.edu.cn/debian-security'
TUNA_PYPI = 'https://pypi.tuna.tsinghua.edu.cn/simple'
OFFICIAL_DEBIAN = 'http://deb.debian.org/debian'
OFFICIAL_SECURITY = 'http://deb.debian.org/debian-security'
OFFICIAL_LIBREOFFICE = 'https://downloadarchive.documentfoundation.org/libreoffice/old'


def _find_sh():
    """查找POSIX sh；Windows下排除System32中的WSL入口，优先Git自带sh。"""
    found = shutil.which('sh')
    if found and 'system32' not in found.lower():
        return found
    git = shutil.which('git')
    if git:
        candidate = Path(git).resolve().parents[1] / 'bin' / 'sh.exe'
        if candidate.exists():
            return str(candidate)
    return None


SH = _find_sh()
IMAGES = ('python', 'node', 'nginx', 'postgres', 'qdrant')
RUN_ID = '20261012-202655-0843c292'


def test_production_isolation():
    text = (ROOT / 'compose.p5.yaml').read_text(encoding='utf-8')
    assert 'build:' not in text and 'compose-p4' not in text
    assert '10.9.14.171:80:8080' in text
    assert text.count('platform: linux/arm64') == 5
    assert '5432:5432' not in text and '6333:6333' not in text
    assert '/data/policy-platform/config/' in text
    assert text.count('policy-platform/backend:p5-20261012-arm64') == 2
    for volume in ('postgres_data', 'qdrant_data', 'knowledge_files', 'material_files', 'app_logs'):
        assert f'  {volume}:' in text


def test_lock_and_build_gate():
    lock = json.loads(
        (ROOT / 'deploy/p5-images.json').read_text(encoding='utf-8'))
    assert lock['platform'] == 'linux/arm64'
    assert all('@sha256:' in value for value in lock['sources'].values())
    script = (ROOT / 'scripts/build-p5-arm64.ps1').read_text(encoding='utf-8-sig')
    assert 'elseif ($BuildAndExport)' in script
    assert 'imagetools inspect --raw' in script
    assert 'ManifestRegistry' in script and "'policy-p5-arm64'" in script
    assert "'--builder',$builder" in script
    assert 'docker pull' not in script and 'docker tag' not in script and 'image save' not in script
    assert '--load' not in script and '--use' not in script and 'prune' not in script
    assert 'manifest-evidence.json' in script and 'checked_at_utc' in script
    assert 'v0.21.0' in script
    # Buildx v0.23无inspect --format；构建器检查必须走ls --format json并按Version字段核对。
    assert 'inspect $builder --format' not in script and 'buildx ls --format json' in script
    assert '$node.Version' in script and "'linux/arm64'" in script
    # 复用仅显式启用；默认仍联网预检，正式构建仍取锁定摘要，不关闭TLS。
    assert "[string]$ReuseVerifiedManifest = ''" in script
    assert 'if ($ReuseVerifiedManifest) { $reuse = Invoke-ManifestReuse } else { Invoke-ManifestChecks }' in script
    assert "p5-manifest-reuse.ps1" in script and 'manifest-reuse.json' in script and 'reused-manifest' in script
    assert 'manifest_mode=$manifestMode' in script and 'manifest_source=$manifestSource' in script
    assert '-ReuseVerifiedManifest不联网，不能同时指定-ManifestRegistry' in script
    assert 'PYTHON_IMAGE=$($lock.sources.python)' in script and 'BASE_IMAGE=$($lock.sources.$name)' in script
    reuse = REUSE_SCRIPT.read_text(encoding='utf-8-sig')
    sources = SOURCES_SCRIPT.read_text(encoding='utf-8-sig')
    helpers = [path.read_text(encoding='utf-8')
               for path in (MIRROR_CHECK, VERIFY_BACKEND)]
    for text in (script, reuse, sources, *helpers):
        assert 'insecure' not in text.lower() and 'tls' not in text.lower()
    # 后端复用仅显式启用并经校验器；构建器内嵌配置必须与TOML一致。
    assert "[string]$ReuseBackendFrom = ''" in script and 'p5-verify-backend-tar.py' in script
    assert 'Confirm-BuildkitConfig $node' in script and 'buildkitd-effective.toml' in script
    assert 'backend_mode=$backendMode' in script and 'backend_source=$backendSource' in script
    # PowerShell 5.1按ANSI读取无BOM脚本，中文会乱码，三个脚本都必须带BOM。
    for path in (BUILD_SCRIPT, REUSE_SCRIPT, SOURCES_SCRIPT):
        assert path.read_bytes()[:3] == b'\xef\xbb\xbf', path
    # 下载源：先校验后建目录，参数只追加到后端构建，实际源写入元数据与日志。
    assert script.index(
        'Get-P5BuildSources') < script.index('New-Item -ItemType Directory -Path $dest')
    assert "[ValidateSet('official','tuna')][string]$AptMirror = 'official'" in script
    assert "[ValidateSet('official','tuna')][string]$AptSecurityMirror = 'official'" in script
    assert '(@(\'--build-arg\',"PYTHON_IMAGE=$($lock.sources.python)") + $sources.build_args)' in script
    assert 'build-sources.json' in script and 'build_sources=$buildSources' in script
    assert '[Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)' in script
    assert 'gc = false' in (
        ROOT / 'deploy/buildkit-p5.toml').read_text(encoding='utf-8')


HUAWEI_MIRROR = '2a6bf1988cb6428c877f723ec7530dbc.mirror.swr.myhuaweicloud.com'
DAOCLOUD_MIRROR = 'docker.m.daocloud.io'
MIRROR_CHECK = ROOT / 'scripts/p5-mirror-check.py'
VERIFY_BACKEND = ROOT / 'scripts/p5-verify-backend-tar.py'


def test_buildkit_mirrors_are_ordered_fallbacks():
    raw = (ROOT / 'deploy/buildkit-p5.toml').read_bytes()
    # buildx按TOML解析后嵌入构建器：须为合法TOML、无BOM。
    assert raw[:3] != b'\xef\xbb\xbf'
    config = tomllib.loads(raw.decode('utf-8'))
    mirrors = config['registry']['docker.io']['mirrors']
    # 顺序即优先级：华为云优先，DaoCloud备用；只写主机名，不写协议、路径，也不配置http或跳过证书。
    assert mirrors == [HUAWEI_MIRROR, DAOCLOUD_MIRROR]
    assert set(config['registry']) == {'docker.io'}
    assert set(config['registry']['docker.io']) == {'mirrors'}
    assert config['worker']['oci'] == {'max-parallelism': 2, 'gc': False}


def _load_script_module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _sha(data):
    return 'sha256:' + hashlib.sha256(data).hexdigest()


class _FakeRegistry:
    """按摘要返回预置内容的离线Registry；可用overrides模拟镜像站返回被篡改的内容。"""

    def __init__(self, blobs, overrides=None):
        self.blobs, self.overrides = blobs, overrides or {}

    def request(self, method, repo, kind, digest, accept=None):
        body = self.overrides.get(digest, self.blobs[digest])
        return 200, {'Content-Length': str(len(body))}, body if method == 'GET' else b''


def _registry_image(arch='arm64'):
    layer = b'layer-bytes'
    config = json.dumps({'architecture': arch, 'os': 'linux', 'rootfs': {
                        'diff_ids': [_sha(b'x')]}}).encode()
    manifest = json.dumps({'config': {'digest': _sha(config), 'size': len(config)},
                           'layers': [{'digest': _sha(layer), 'size': len(layer)}]}).encode()
    index = json.dumps({'manifests': [
        {'digest': _sha(b'amd'), 'platform': {
            'os': 'linux', 'architecture': 'amd64'}},
        {'digest': _sha(manifest), 'platform': {'os': 'linux', 'architecture': 'arm64', 'variant': 'v8'}}]}).encode()
    blobs = {_sha(item): item for item in (layer, config, manifest, index)}
    return blobs, f'node:22-test@{_sha(index)}', _sha(manifest)


def test_mirror_check_accepts_matching_digests():
    module = _load_script_module(MIRROR_CHECK, 'p5_mirror_check')
    blobs, reference, child = _registry_image()
    result = module.check_image(_FakeRegistry(
        blobs), 'node', reference, {child})
    assert result['status'] == 'PASS', result
    assert result['repository'] == 'library/node' and result['arm64_digest'] == child
    assert module.repository('qdrant/qdrant:v1@' +
                             'sha256:' + 'a' * 64)[0] == 'qdrant/qdrant'


@pytest.mark.parametrize(('case', 'stage'), [
    pytest.param('evidence', 'index', id='arm64-differs-from-evidence'),
    pytest.param('tampered-index', 'index', id='index-content-tampered'),
    pytest.param('amd64-config', 'config', id='config-not-arm64'),
])
def test_mirror_check_rejects_mismatch(case, stage):
    module = _load_script_module(MIRROR_CHECK, 'p5_mirror_check')
    blobs, reference, child = _registry_image(
        'amd64' if case == 'amd64-config' else 'arm64')
    evidence = {'sha256:' + 'f' * 64} if case == 'evidence' else {child}
    overrides = {reference.split(
        '@')[1]: b'{"manifests": []}'} if case == 'tampered-index' else None
    result = module.check_image(_FakeRegistry(
        blobs, overrides), 'node', reference, evidence)
    assert result['status'] == 'FAIL' and result['stage'] == stage, result


@pytest.mark.parametrize('arguments', [
    pytest.param(['--mirror', 'https://docker.m.daocloud.io'],
                 id='scheme-in-host'),
    pytest.param(['--mirror', 'docker.m.daocloud.io/v2'], id='path-in-host'),
    pytest.param(['--mirror', DAOCLOUD_MIRROR, '--images',
                 'redis'], id='image-not-in-lock'),
])
def test_mirror_check_rejects_bad_arguments(arguments):
    module = _load_script_module(MIRROR_CHECK, 'p5_mirror_check')
    with pytest.raises(SystemExit) as error:
        module.main(arguments)
    assert error.value.code == 2


def test_p5_credentials_are_new_and_isolated(tmp_path):
    spec = importlib.util.spec_from_file_location(
        'prepare_p5', ROOT / 'scripts/prepare-compose.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    source = tmp_path / 'models.env'
    source.write_text(
        'POLICY_EMBEDDING_URL=http://model/e\nPOLICY_RERANK_URL=http://model/r\nPOLICY_GENERATOR_URL=http://model/g\nPLATFORM_DATABASE_URL=old-account\n', encoding='utf-8')
    target = tmp_path / 'config'
    result = module.prepare(source, target, stage='p5')
    assert result['namespace'].startswith('policy_platform_p5_')
    assert not (target / 'runtime-external.env').exists()
    runtime = (target / 'runtime.env').read_text(encoding='utf-8')
    assert 'old-account' not in runtime
    assert '/usr/local/bin/soffice' in runtime
    assert "PLATFORM_COOKIE_SECURE='false'" in runtime


def _write_ps_utf8(path, text):
    """模拟PowerShell 5.1 Set-Content -Encoding UTF8的落盘格式：BOM、CRLF、末尾换行。"""
    path.write_bytes(b'\xef\xbb\xbf' +
                     (text.replace('\n', '\r\n') + '\r\n').encode('utf-8'))


def _make_record(tmp_path):
    """生成一份合法的历史联网预检记录；摘要按原始manifest字节真实计算。"""
    root = tmp_path / 'var' / 'p5-delivery'
    run = root / RUN_ID
    run.mkdir(parents=True)
    sources, evidence = {}, []
    for i, name in enumerate(IMAGES):
        arm = {'mediaType': 'application/vnd.oci.image.manifest.v1+json', 'size': 1000 + i,
               'digest': 'sha256:' + hashlib.sha256(f'{name}-arm64'.encode()).hexdigest(),
               'platform': {'architecture': 'arm64', 'os': 'linux', 'variant': 'v8'}}
        if name == 'qdrant':
            arm['platform'].pop('variant')
        amd = {'mediaType': 'application/vnd.oci.image.manifest.v1+json', 'size': 900 + i,
               'digest': 'sha256:' + hashlib.sha256(f'{name}-amd64'.encode()).hexdigest(),
               'platform': {'architecture': 'amd64', 'os': 'linux'}}
        index = {'manifests': [
            amd, arm], 'mediaType': 'application/vnd.oci.image.index.v1+json', 'schemaVersion': 2}
        # qdrant的原始manifest为多行JSON，其余为单行，与真实镜像站返回一致。
        raw = json.dumps(index, indent=3) if name == 'qdrant' else json.dumps(
            index, separators=(',', ':'))
        digest = 'sha256:' + hashlib.sha256(raw.encode()).hexdigest()
        ref = f'qdrant/qdrant@{digest}' if name == 'qdrant' else f'{name}:test@{digest}'
        sources[name] = ref
        _write_ps_utf8(run / f'{name}-manifest.json', raw)
        (run / f'{name}-manifest.stderr.log').write_bytes(b'\xef\xbb\xbf')
        evidence.append({'image': name, 'original_reference': ref, 'query_reference': f'mirror.example/{name}@{digest}',
                         'checked_at_utc': f'2026-10-12T12:26:5{i}.0000000Z', 'arm64': [arm]})
    lock = tmp_path / 'p5-images.json'
    lock.write_text(json.dumps({'description': '测试锁', 'platform': 'linux/arm64', 'sources': sources, 'outputs': {}},
                               ensure_ascii=False, indent=2), encoding='utf-8')
    (run / 'source-lock.json').write_bytes(lock.read_bytes())
    _write_ps_utf8(run / 'manifest-evidence.json',
                   json.dumps(evidence, indent=2))
    _write_ps_utf8(run / 'completed.json', json.dumps(
        {'completed_at_utc': '2026-10-12T12:27:00.6617430Z', 'builder': 'policy-p5-arm64', 'probe': 'None', 'build': False}))
    return root, run, lock


def _confirm(root, lock, source=RUN_ID, location=None, process_cwd=None):
    """在powershell中加载校验函数；路径经环境变量传入，避免引号转义。

    location：PowerShell当前位置（Set-Location）；process_cwd：进程工作目录。
    二者不同时可复现脚本Set-Location后.NET仍按旧目录解析相对路径的情形。
    """
    command = (
        "[Console]::OutputEncoding=[Text.Encoding]::UTF8; $ErrorActionPreference='Stop'; "
        f". '{REUSE_SCRIPT}'; "
        "if ($env:P5_LOCATION) { Set-Location -LiteralPath $env:P5_LOCATION }; "
        "try { $r = Confirm-VerifiedManifestRecord -Source $env:P5_SOURCE -DeliveryRoot $env:P5_ROOT "
        "-LockPath $env:P5_LOCK -Builder 'policy-p5-arm64'; 'PASS ' + ($r | ConvertTo-Json -Depth 10 -Compress) } "
        "catch { 'FAIL ' + $_.Exception.Message; exit 2 }"
    )
    env = {**os.environ, 'P5_SOURCE': str(source), 'P5_ROOT': str(root), 'P5_LOCK': str(lock),
           'P5_LOCATION': str(location or '')}
    done = subprocess.run([POWERSHELL, '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-Command', command],
                          capture_output=True, text=True, encoding='utf-8', env=env, timeout=120, cwd=process_cwd)
    return done.returncode, done.stdout.strip()


needs_powershell = pytest.mark.skipif(
    POWERSHELL is None, reason='需要PowerShell执行复用校验函数')


@needs_powershell
def test_manifest_reuse_accepts_valid_record(tmp_path):
    root, _, lock = _make_record(tmp_path)
    code, out = _confirm(root, lock)
    assert code == 0 and out.startswith('PASS '), out
    report = json.loads(out[5:])
    assert report['result'] == 'PASS' and report['source_run'] == RUN_ID and report['source_probe'] == 'None'
    assert report['platform'] == 'linux/arm64' and len(report['files']) == 13
    images = {item['image']: item for item in report['images']}
    assert set(images) == set(IMAGES)
    assert all(item['manifest_sha256_recomputed'] ==
               item['index_digest'] for item in images.values())
    platforms = {name: (item['arm64'] if isinstance(item['arm64'], dict) else item['arm64'][0])[
        'platform'] for name, item in images.items()}
    assert platforms['python'] == 'linux/arm64/v8' and platforms['qdrant'] == 'linux/arm64'
    # 运行编号与完整目录两种写法均可。
    code, out = _confirm(root, lock, source=root / RUN_ID)
    assert code == 0, out


@needs_powershell
def test_manifest_reuse_relative_paths_follow_powershell_location(tmp_path):
    """回归：构建脚本以相对路径传入且进程工作目录不同时，不得误报锁文件无法解析。"""
    _make_record(tmp_path)
    elsewhere = tmp_path / 'elsewhere'
    elsewhere.mkdir()
    code, out = _confirm('var/p5-delivery', 'p5-images.json',
                         location=tmp_path, process_cwd=elsewhere)
    assert code == 0 and out.startswith('PASS '), out
    # 锁文件确实缺失时明确报告缺失，而非“无法解析JSON”。
    code, out = _confirm('var/p5-delivery', 'missing-lock.json',
                         location=tmp_path, process_cwd=elsewhere)
    assert code == 2 and out.startswith(
        'FAIL [REUSE-LOCK-MISMATCH]') and 'missing-lock.json' in out, out


def _tamper_manifest_digest(root, run, lock):
    text = (run / 'python-manifest.json').read_text(encoding='utf-8-sig')
    _write_ps_utf8(run / 'python-manifest.json',
                   text.strip().replace('"size":1000', '"size":1001'))


def _change_current_lock(root, run, lock):
    data = json.loads(lock.read_text(encoding='utf-8'))
    data['sources']['node'] = data['sources']['node'].split(
        '@')[0] + '@sha256:' + '0' * 64
    lock.write_text(json.dumps(data, ensure_ascii=False,
                    indent=2), encoding='utf-8')


def _change_evidence_arm64(root, run, lock):
    evidence = json.loads(
        (run / 'manifest-evidence.json').read_text(encoding='utf-8-sig'))
    evidence[3]['arm64'][0]['digest'] = 'sha256:' + 'f' * 64
    _write_ps_utf8(run / 'manifest-evidence.json',
                   json.dumps(evidence, indent=2))


def _drop_evidence_image(root, run, lock):
    evidence = json.loads(
        (run / 'manifest-evidence.json').read_text(encoding='utf-8-sig'))
    _write_ps_utf8(run / 'manifest-evidence.json',
                   json.dumps(evidence[:4], indent=2))


def _set_platform(root, run, lock):
    data = json.loads(lock.read_text(encoding='utf-8'))
    data['platform'] = 'linux/amd64'
    lock.write_text(json.dumps(data, ensure_ascii=False,
                    indent=2), encoding='utf-8')
    (run / 'source-lock.json').write_bytes(lock.read_bytes())


def _set_completed(**changes):
    def mutate(root, run, lock):
        data = json.loads(
            (run / 'completed.json').read_text(encoding='utf-8-sig'))
        data.update(changes)
        _write_ps_utf8(run / 'completed.json', json.dumps(data))
    return mutate


def _delete(name):
    return lambda root, run, lock: (run / name).unlink()


def _write_stderr(root, run, lock):
    _write_ps_utf8(run / 'nginx-manifest.stderr.log',
                   'ERROR: unexpected status from HEAD request: 502 Bad Gateway')


def _mark_as_reused(root, run, lock):
    _write_ps_utf8(run / 'manifest-reuse.json', '{}')


@needs_powershell
@pytest.mark.parametrize(('mutate', 'code'), [
    pytest.param(_tamper_manifest_digest, 'REUSE-DIGEST-MISMATCH',
                 id='manifest-content-tampered'),
    pytest.param(_change_current_lock, 'REUSE-LOCK-MISMATCH',
                 id='lock-digest-changed'),
    pytest.param(_change_evidence_arm64, 'REUSE-ARM64-MISMATCH',
                 id='arm64-digest-mismatch'),
    pytest.param(_drop_evidence_image, 'REUSE-EVIDENCE',
                 id='evidence-missing-image'),
    pytest.param(_set_platform, 'REUSE-PLATFORM', id='platform-not-arm64'),
    pytest.param(_delete('node-manifest.json'),
                 'REUSE-INCOMPLETE', id='missing-manifest-file'),
    pytest.param(_delete('manifest-evidence.json'),
                 'REUSE-INCOMPLETE', id='missing-evidence'),
    pytest.param(_delete('source-lock.json'),
                 'REUSE-INCOMPLETE', id='missing-source-lock'),
    pytest.param(_delete('completed.json'), 'REUSE-NOT-SUCCESS',
                 id='failed-run-no-completed'),
    pytest.param(_write_stderr, 'REUSE-NOT-SUCCESS', id='failed-run-stderr'),
    pytest.param(_set_completed(probe='Export'),
                 'REUSE-NOT-SUCCESS', id='export-probe-record'),
    pytest.param(_set_completed(builder='other-builder'),
                 'REUSE-NOT-SUCCESS', id='other-builder'),
    pytest.param(_set_completed(manifest_mode='reused'),
                 'REUSE-NOT-SUCCESS', id='chained-reuse-mode'),
    pytest.param(_mark_as_reused, 'REUSE-NOT-SUCCESS',
                 id='chained-reuse-file'),
])
def test_manifest_reuse_rejects_unreliable_record(tmp_path, mutate, code):
    root, run, lock = _make_record(tmp_path)
    mutate(root, run, lock)
    status, out = _confirm(root, lock)
    assert status == 2 and out.startswith(f'FAIL [{code}]'), out


def _instructions(text):
    """把Dockerfile按指令切分，合并反斜杠续行，跳过空行与注释。"""
    result, buffer = [], ''
    for line in text.splitlines():
        if not buffer and (not line.strip() or line.lstrip().startswith('#')):
            continue
        if line.endswith('\\'):
            buffer += line[:-1] + ' '
            continue
        result.append((buffer + line).strip())
        buffer = ''
    return result


def test_backend_dockerfile_encoding_and_pins():
    raw = DOCKERFILE.read_bytes()
    # 严格UTF-8、无BOM、LF换行；中文注释不得含替换字符。
    assert raw[:3] != b'\xef\xbb\xbf' and b'\r' not in raw
    text = raw.decode('utf-8')
    assert '\ufffd' not in text
    assert f'ARG PYTHON_IMAGE={PYTHON_IMAGE}\n' in text and 'FROM ${PYTHON_IMAGE}\n' in text
    lock = json.loads(
        (ROOT / 'deploy/p5-images.json').read_text(encoding='utf-8'))
    assert lock['sources']['python'] == PYTHON_IMAGE
    assert text.count(f'version={LIBREOFFICE_VERSION};') == 1
    assert 'amd64) dir=x86_64; pkg=x86-64; sum=' + \
        LIBREOFFICE_SUMS['amd64'] in text
    assert 'arm64) dir=aarch64; pkg=aarch64; sum=' + \
        LIBREOFFICE_SUMS['arm64'] in text
    # 不允许任何绕过签名、哈希或证书校验的写法。
    for forbidden in ('--allow-unauthenticated', 'trusted=yes', 'AllowInsecureRepositories',
                      'AllowDowngradeToInsecureRepositories', 'Check-Valid-Until', '--insecure',
                      'curl -k', '--trusted-host', 'ARG LIBREOFFICE_VERSION', 'ARG LIBREOFFICE_SHA'):
        assert forbidden not in text, forbidden
    # BuildKit内置前端已支持RUN --mount；不加syntax指令，避免构建时联网拉取前端镜像。
    assert '# syntax=' not in text


def test_backend_dockerfile_layers_and_cache_mounts():
    steps = _instructions(DOCKERFILE.read_text(encoding='utf-8'))
    runs = [i for i, step in enumerate(steps) if step.startswith('RUN ')]
    apt = [i for i in runs if 'apt-get' in steps[i]]
    lo = [i for i in runs if 'LibreOffice_' in steps[i]]
    pip = [i for i in runs if 'pip install' in steps[i]]
    assert len(apt) == len(lo) == len(pip) == 1 and apt[0] < lo[0] < pip[0]
    apt_step, lo_step, pip_step = steps[apt[0]], steps[lo[0]], steps[pip[0]]
    # apt层：重试与超时、独立缓存目录、加锁共享；源配置先切换后恢复，清理索引。
    for needle in ('Acquire::Retries=5', 'Acquire::http::Timeout=60', 'Acquire::https::Timeout=60',
                   'Dir::Cache::Archives=/var/cache/policy-apt/archives',
                   '--mount=type=cache,id=policy-backend-apt-${TARGETARCH},target=/var/cache/policy-apt,sharing=locked',
                   '--mount=type=bind,source=deploy/apt-sources.sh,target=/tmp/apt-sources.sh',
                   'fonts-noto-cjk', 'rm -rf /var/lib/apt/lists/*'):
        assert needle in apt_step, needle
    assert apt_step.index('apt-sources.sh apply') < apt_step.index(
        ' install ') < apt_step.index('apt-sources.sh restore')
    assert 'LibreOffice' not in apt_step and 'curl -fL' not in apt_step
    # LibreOffice层：版本与SHA256在本层固定，下载前后均校验，失败不触发apt层重做。
    assert 'apt-get' not in lo_step and lo_step.count('sha256sum -c -') == 3
    assert '--mount=type=cache,id=policy-backend-libreoffice-${TARGETARCH},target=/var/cache/policy-libreoffice,sharing=locked' in lo_step
    assert '"${LIBREOFFICE_BASE_URL:-' + OFFICIAL_LIBREOFFICE + '}"' in lo_step
    assert '${base%/}/$version/deb/$dir/$file' in lo_step and 'https://*)' in lo_step
    assert 'soffice --version | grep -F "LibreOffice $version "' in lo_step
    assert '--index-url "$PYPI_INDEX_URL"' in pip_step and '--no-cache-dir' in pip_step
    # 每个源参数在最终阶段声明，且紧挨在使用它的层之前，改动下载源不使前面的层失效。
    position = {step.split('=')[0][4:]: i for i, step in enumerate(
        steps) if step.startswith('ARG ')}
    assert position['PYTHON_IMAGE'] < steps.index(
        'FROM ${PYTHON_IMAGE}') < position['TARGETARCH']
    assert position['TARGETARCH'] < position['DEBIAN_MIRROR'] < position['DEBIAN_SECURITY_MIRROR'] < apt[0]
    assert apt[0] < position['LIBREOFFICE_BASE_URL'] < lo[0] < position['PYPI_INDEX_URL'] < pip[0]
    # 缓存目录不得被复制进镜像。
    assert not any(step.startswith('COPY')
                   and 'policy-apt' in step for step in steps)


SAMPLE_SOURCES = (
    'Types: deb\n'
    '# http://snapshot.debian.org/archive/debian/20250224T000000Z\n'
    f'URIs: {OFFICIAL_DEBIAN}\n'
    'Suites: bookworm bookworm-updates\n'
    'Components: main\n'
    'Signed-By: /usr/share/keyrings/debian-archive-keyring.gpg\n'
    '\n'
    'Types: deb\n'
    '# http://snapshot.debian.org/archive/debian-security/20250224T000000Z\n'
    f'URIs: {OFFICIAL_SECURITY}\n'
    'Suites: bookworm-security\n'
    'Components: main\n'
    'Signed-By: /usr/share/keyrings/debian-archive-keyring.gpg\n'
)
needs_sh = pytest.mark.skipif(SH is None, reason='需要POSIX sh执行apt-sources.sh')


def _apt_sources(path, action, main='', security=''):
    """对临时源文件执行apt-sources.sh；返回(退出码, stdout+stderr)。"""
    env = {**os.environ, 'APT_SOURCES_FILE': path.as_posix(),
           'DEBIAN_MIRROR': main, 'DEBIAN_SECURITY_MIRROR': security}
    done = subprocess.run([SH, APT_SOURCES.as_posix(), action],
                          capture_output=True, env=env, timeout=60)
    output = (done.stdout + done.stderr).decode('utf-8', errors='replace')
    return done.returncode, output


def _uris(path):
    return [line for line in path.read_text(encoding='utf-8').splitlines() if line.startswith('URIs:')]


@needs_sh
@pytest.mark.parametrize(('main', 'security', 'expected'), [
    pytest.param('', '', [OFFICIAL_DEBIAN,
                 OFFICIAL_SECURITY], id='default-official'),
    pytest.param(TUNA_DEBIAN, '', [
                 TUNA_DEBIAN, OFFICIAL_SECURITY], id='main-only-security-stays-official'),
    pytest.param('', TUNA_SECURITY, [
                 OFFICIAL_DEBIAN, TUNA_SECURITY], id='security-only'),
    pytest.param(TUNA_DEBIAN + '/', TUNA_SECURITY,
                 [TUNA_DEBIAN, TUNA_SECURITY], id='both-trailing-slash'),
])
def test_apt_sources_apply_and_restore(tmp_path, main, security, expected):
    path = tmp_path / 'debian.sources'
    path.write_bytes(SAMPLE_SOURCES.encode('utf-8'))
    code, out = _apt_sources(path, 'apply', main, security)
    assert code == 0, out
    assert _uris(path) == [f'URIs: {uri}' for uri in expected]
    text = path.read_text(encoding='utf-8')
    # 只改URIs行：Suites与Signed-By保持不变，签名校验不受影响。
    assert text.count(
        'Signed-By: /usr/share/keyrings/debian-archive-keyring.gpg') == 2
    assert 'Suites: bookworm bookworm-updates' in text and 'Suites: bookworm-security' in text
    assert f'[apt-sources] URIs: {expected[0]}' in out and f'[apt-sources] URIs: {expected[1]}' in out
    if not main and not security:
        assert path.read_bytes() == SAMPLE_SOURCES.encode('utf-8')
    code, out = _apt_sources(path, 'restore')
    assert code == 0, out
    assert path.read_bytes() == SAMPLE_SOURCES.encode('utf-8')
    assert not (tmp_path / 'debian.sources.policy-orig').exists()


@needs_sh
@pytest.mark.parametrize(('content', 'main', 'message'), [
    pytest.param(SAMPLE_SOURCES, 'ftp://mirror.example/debian',
                 '镜像地址格式不合法', id='non-http-scheme'),
    pytest.param(SAMPLE_SOURCES, 'https://mirror.example/a#b',
                 '镜像地址格式不合法', id='sed-delimiter'),
    pytest.param(SAMPLE_SOURCES, 'https://mirror.example/a b',
                 '镜像地址格式不合法', id='space'),
    pytest.param(SAMPLE_SOURCES.replace(f'URIs: {OFFICIAL_DEBIAN}\n', 'URIs: http://other.example/debian\n'),
                 TUNA_DEBIAN, '基础镜像源格式变化', id='official-line-missing'),
    pytest.param(SAMPLE_SOURCES + f'\nTypes: deb-src\nURIs: {OFFICIAL_DEBIAN}\n',
                 TUNA_DEBIAN, '基础镜像源格式变化', id='official-line-duplicated'),
])
def test_apt_sources_rejects_unexpected_input(tmp_path, content, main, message):
    path = tmp_path / 'debian.sources'
    path.write_bytes(content.encode('utf-8'))
    code, out = _apt_sources(path, 'apply', main)
    assert code != 0 and message in out, out
    # 失败时源文件未被改写，不会以半替换状态继续。
    assert path.read_bytes() == content.encode('utf-8')


@needs_sh
def test_apt_sources_usage_errors(tmp_path):
    path = tmp_path / 'debian.sources'
    path.write_bytes(SAMPLE_SOURCES.encode('utf-8'))
    code, out = _apt_sources(path, 'restore')
    assert code != 0 and '缺少备份' in out, out
    code, out = _apt_sources(path, 'other')
    assert code != 0 and '用法' in out, out
    code, out = _apt_sources(
        tmp_path / 'missing.sources', 'apply', TUNA_DEBIAN)
    assert code != 0 and '源文件不存在' in out, out


def _sources(arguments='', dockerfile=DOCKERFILE, apt=APT_SOURCES):
    """在powershell中调用Get-P5BuildSources；返回(退出码, 输出)。"""
    command = (
        "[Console]::OutputEncoding=[Text.Encoding]::UTF8; $ErrorActionPreference='Stop'; "
        f". '{SOURCES_SCRIPT}'; "
        f"try {{ $r = Get-P5BuildSources {arguments} -DockerfilePath $env:P5_DOCKERFILE -AptSourcesPath $env:P5_APT; "
        "'PASS ' + ($r | ConvertTo-Json -Depth 5 -Compress) } catch { 'FAIL ' + $_.Exception.Message; exit 2 }"
    )
    env = {**os.environ, 'P5_DOCKERFILE': str(dockerfile), 'P5_APT': str(apt)}
    done = subprocess.run([POWERSHELL, '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-Command', command],
                          capture_output=True, text=True, encoding='utf-8', env=env, timeout=120)
    return done.returncode, done.stdout.strip()


def _arg_values(build_args):
    assert build_args[0::2] == ['--build-arg'] * 4
    return dict(item.split('=', 1) for item in build_args[1::2])


@needs_powershell
def test_build_sources_mapping():
    code, out = _sources()
    assert code == 0 and out.startswith('PASS '), out
    result = json.loads(out[5:])
    # 默认全部为空参数，Dockerfile回落到官方源，与P4构建一致。
    assert _arg_values(result['build_args']) == {
        'DEBIAN_MIRROR': '', 'DEBIAN_SECURITY_MIRROR': '', 'LIBREOFFICE_BASE_URL': '', 'PYPI_INDEX_URL': ''}
    record = result['record']
    assert record['apt_mirror'] == 'official' and record['debian_uri'] == OFFICIAL_DEBIAN
    assert record['debian_security_uri'] == OFFICIAL_SECURITY and record['libreoffice_base_url'] == OFFICIAL_LIBREOFFICE
    assert record['libreoffice_version'] == LIBREOFFICE_VERSION
    assert record['libreoffice_arm64_sha256'] == LIBREOFFICE_SUMS['arm64']
    assert record['dockerfile_sha256'] == hashlib.sha256(
        DOCKERFILE.read_bytes()).hexdigest()
    # 只指定主仓库镜像时security仍走官方源。
    code, out = _sources(f'-AptMirror tuna -PipIndexUrl {TUNA_PYPI}')
    assert code == 0, out
    result = json.loads(out[5:])
    assert _arg_values(result['build_args']) == {
        'DEBIAN_MIRROR': TUNA_DEBIAN, 'DEBIAN_SECURITY_MIRROR': '', 'LIBREOFFICE_BASE_URL': '', 'PYPI_INDEX_URL': TUNA_PYPI}
    assert result['record']['debian_security_uri'] == OFFICIAL_SECURITY and result['record']['pypi_index_url'] == TUNA_PYPI
    code, out = _sources(
        '-AptMirror tuna -AptSecurityMirror tuna -LibreOfficeBaseUrl https://mirror.example/libreoffice/old')
    assert code == 0, out
    values = _arg_values(json.loads(out[5:])['build_args'])
    assert values['DEBIAN_SECURITY_MIRROR'] == TUNA_SECURITY
    assert values['LIBREOFFICE_BASE_URL'] == 'https://mirror.example/libreoffice/old'


@needs_powershell
@pytest.mark.parametrize(('arguments', 'message'), [
    pytest.param('-PipIndexUrl http://pypi.example/simple',
                 '必须是https地址', id='pip-http'),
    pytest.param('-LibreOfficeBaseUrl http://mirror.example/lo',
                 '必须是https地址', id='libreoffice-http'),
    pytest.param("-LibreOfficeBaseUrl 'https://mirror.example/a;b'",
                 '必须是https地址', id='libreoffice-shell-char'),
    pytest.param('-AptMirror aliyun', 'aliyun', id='unknown-preset'),
])
def test_build_sources_rejects_bad_arguments(arguments, message):
    code, out = _sources(arguments)
    assert code == 2 and out.startswith('FAIL ') and message in out, out


@needs_powershell
@pytest.mark.parametrize(('old', 'new', 'target', 'message'), [
    pytest.param('ARG PYPI_INDEX_URL=\n', '', 'dockerfile',
                 '未声明ARG PYPI_INDEX_URL', id='arg-missing'),
    pytest.param('ARG DEBIAN_MIRROR=\n', '', 'dockerfile',
                 '未声明ARG DEBIAN_MIRROR', id='debian-arg-missing'),
    pytest.param('ARG LIBREOFFICE_BASE_URL=\n', '', 'prepend',
                 '未声明ARG LIBREOFFICE_BASE_URL', id='arg-before-from'),
    pytest.param('"${LIBREOFFICE_BASE_URL:-', '"${OTHER_URL:-',
                 'dockerfile', '声明后未使用LIBREOFFICE_BASE_URL', id='arg-unused'),
    pytest.param('"${DEBIAN_SECURITY_MIRROR:-}"', '""', 'apt',
                 '声明后未使用DEBIAN_SECURITY_MIRROR', id='apt-script-unused'),
])
def test_build_sources_detects_dropped_build_args(tmp_path, old, new, target, message):
    """Dockerfile或apt-sources.sh未真正接收参数时，必须在建交付目录前报错。"""
    dockerfile = DOCKERFILE.read_text(encoding='utf-8')
    apt = APT_SOURCES.read_text(encoding='utf-8')
    assert old in (apt if target == 'apt' else dockerfile)
    if target == 'apt':
        apt = apt.replace(old, new)
    elif target == 'prepend':
        # 移到FROM之前：docker接受该参数但RUN中不可见。
        dockerfile = old + dockerfile.replace(old, '')
    else:
        dockerfile = dockerfile.replace(old, new)
    (tmp_path / 'Dockerfile').write_bytes(dockerfile.encode('utf-8'))
    (tmp_path / 'apt-sources.sh').write_bytes(apt.encode('utf-8'))
    code, out = _sources(dockerfile=tmp_path / 'Dockerfile',
                         apt=tmp_path / 'apt-sources.sh')
    assert code == 2 and message in out, out


FAKE_DOCKER = '''"""测试用假docker：buildx ls返回就绪的专用构建器，其余调用只记录参数并输出一行中文。

bin/buildkitd.toml存在时按buildx的方式以base64放入Nodes[0].Files，模拟创建时嵌入的配置。
"""
import base64, json, pathlib, sys
args = sys.argv[1:]
here = pathlib.Path(__file__).parent
if args[:2] == ['buildx', 'ls']:
    node = {'Status': 'running', 'Platforms': ['linux/arm64'], 'Version': 'v0.21.0'}
    if (here / 'buildkitd.toml').exists():
        node['Files'] = {'buildkitd.toml': base64.b64encode((here / 'buildkitd.toml').read_bytes()).decode()}
    print(json.dumps({'Name': 'policy-p5-arm64', 'Driver': 'docker-container', 'Nodes': [node]}))
    sys.exit(0)
with open(here / 'calls.jsonl', 'a', encoding='utf-8') as handle:
    handle.write(json.dumps(args, ensure_ascii=False) + '\\n')
print('#1 假构建：已挂载。')
'''


def _effective_toml(mirrors):
    """buildx create重新序列化后嵌入构建器的格式（去掉注释、分节展开、键按字母序）。"""
    return ('\n[registry]\n\n  [registry."docker.io"]\n    mirrors = [' + ', '.join(f'"{item}"' for item in mirrors)
            + ']\n\n[worker]\n\n  [worker.oci]\n    gc = false\n    max-parallelism = 2\n')


def _fake_repo(tmp_path, embedded=None):
    """在临时目录搭建最小仓库副本、合法的历史manifest记录与假docker。

    embedded：假构建器内嵌的buildkitd.toml文本；默认按当前TOML的镜像站生成，False表示未内嵌。
    """
    root, run, lock = _make_record(tmp_path)
    data = json.loads(lock.read_text(encoding='utf-8'))
    data['outputs'] = {
        name: f'policy-platform/{name}:test' for name in ('backend', 'web', 'postgres', 'qdrant')}
    lock.write_text(json.dumps(data, ensure_ascii=False,
                    indent=2), encoding='utf-8')
    (run / 'source-lock.json').write_bytes(lock.read_bytes())
    for folder in ('scripts', 'deploy', 'bin'):
        (tmp_path / folder).mkdir()
    for name in ('build-p5-arm64.ps1', 'p5-manifest-reuse.ps1', 'p5-build-sources.ps1', 'p5-verify-backend-tar.py'):
        shutil.copy2(ROOT / 'scripts' / name, tmp_path / 'scripts' / name)
    for name in ('Dockerfile.backend', 'apt-sources.sh', 'buildkit-p5.toml'):
        shutil.copy2(ROOT / 'deploy' / name, tmp_path / 'deploy' / name)
    shutil.copy2(lock, tmp_path / 'deploy' / 'p5-images.json')
    (tmp_path / '.dockerignore').write_text(DOCKERIGNORE, encoding='utf-8')
    (tmp_path / 'bin' / 'fake_docker.py').write_text(FAKE_DOCKER, encoding='utf-8')
    (tmp_path / 'bin' / 'docker.cmd').write_text(
        f'@"{sys.executable}" "%~dp0fake_docker.py" %*\r\n', encoding='ascii')
    if embedded is None:
        mirrors = tomllib.loads((ROOT / 'deploy/buildkit-p5.toml').read_text(
            encoding='utf-8'))['registry']['docker.io']['mirrors']
        embedded = _effective_toml(mirrors)
    if embedded is not False:
        (tmp_path / 'bin' / 'buildkitd.toml').write_text(embedded,
                                                         encoding='utf-8', newline='\n')
    return root, data


def _run_build(tmp_path, *arguments):
    env = {**os.environ, 'PYTHONIOENCODING': 'utf-8',
           'PATH': str(tmp_path / 'bin') + os.pathsep + os.environ.get('PATH', '')}
    done = subprocess.run([POWERSHELL, '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-File',
                           str(tmp_path / 'scripts' / 'build-p5-arm64.ps1'), *arguments],
                          capture_output=True, text=True, encoding='utf-8', errors='replace', env=env, timeout=180)
    return done.returncode, done.stdout + done.stderr


needs_windows_powershell = pytest.mark.skipif(
    POWERSHELL is None or os.name != 'nt', reason='假docker以.cmd实现，需要Windows PowerShell')


@needs_windows_powershell
def test_build_script_passes_mirror_args_to_backend_build(tmp_path):
    """端到端：清华镜像参数经脚本真实传给docker buildx的后端构建，并写入日志与元数据。"""
    root, lock = _fake_repo(tmp_path)
    code, out = _run_build(tmp_path, '-BuildAndExport', '-ReuseVerifiedManifest', RUN_ID,
                           '-AptMirror', 'tuna', '-PipIndexUrl', TUNA_PYPI)
    assert code == 0, out
    runs = [path for path in root.iterdir() if path.name != RUN_ID]
    assert len(runs) == 1
    dest = runs[0]
    calls = [json.loads(line) for line in (
        tmp_path / 'bin' / 'calls.jsonl').read_text(encoding='utf-8').splitlines()]
    assert len(calls) == 4
    backend = next(
        call for call in calls if 'deploy/Dockerfile.backend' in call)
    pairs = {backend[i + 1]
             for i, item in enumerate(backend[:-1]) if item == '--build-arg'}
    assert pairs == {f'PYTHON_IMAGE={lock["sources"]["python"]}', f'DEBIAN_MIRROR={TUNA_DEBIAN}',
                     'DEBIAN_SECURITY_MIRROR=', 'LIBREOFFICE_BASE_URL=', f'PYPI_INDEX_URL={TUNA_PYPI}'}
    assert backend[:4] == ['buildx', '--builder', 'policy-p5-arm64', 'build']
    assert backend[backend.index('--platform') +
                   1] == 'linux/arm64' and backend[-1] == '.'
    # 其他镜像不接收下载源参数。
    for call in calls:
        if call is not backend:
            assert not any(
                'MIRROR' in item or 'INDEX_URL' in item for item in call), call
    sources = json.loads(
        (dest / 'build-sources.json').read_text(encoding='utf-8-sig'))
    assert sources['apt_mirror'] == 'tuna' and sources['debian_uri'] == TUNA_DEBIAN
    assert sources['apt_security_mirror'] == 'official' and sources['debian_security_uri'] == OFFICIAL_SECURITY
    assert sources['pypi_index_url'] == TUNA_PYPI and sources['libreoffice_base_url'] == OFFICIAL_LIBREOFFICE
    assert sources['libreoffice_arm64_sha256'] == LIBREOFFICE_SUMS['arm64']
    assert sources['apt_sources_sha256'] == hashlib.sha256(
        APT_SOURCES.read_bytes()).hexdigest()
    completed = json.loads(
        (dest / 'completed.json').read_text(encoding='utf-8-sig'))
    assert completed['manifest_mode'] == 'reused' and completed['build_sources'] == sources
    assert completed['backend_mode'] == 'built' and completed['backend_source'] is None
    # 构建器内嵌配置与TOML一致，生效配置副本写入交付目录。
    assert f'[buildkitd] 生效配置：mirrors={HUAWEI_MIRROR},{DAOCLOUD_MIRROR};gc=false;max-parallelism=2' in out
    assert HUAWEI_MIRROR in (
        dest / 'buildkitd-effective.toml').read_text(encoding='utf-8-sig')
    log = (dest / 'backend-build.log').read_text(encoding='utf-8-sig')
    assert log.startswith('[sources] apt_mirror=tuna')
    assert f'[sources] debian_uri={TUNA_DEBIAN}' in log and f'[sources] pypi_index_url={TUNA_PYPI}' in log
    # docker输出按UTF-8解码，行尾中文句号不再被吞。
    assert '#1 假构建：已挂载。' in log


# 2026-10-12运行时构建器policy-p5-arm64实际内嵌的配置（取自builder.json）：只有DaoCloud。
OLD_EMBEDDED = ('\n[registry]\n\n  [registry."docker.io"]\n    mirrors = ["docker.m.daocloud.io"]\n\n'
                '[worker]\n\n  [worker.oci]\n    gc = false\n    max-parallelism = 2\n')


@needs_windows_powershell
@pytest.mark.parametrize(('embedded', 'message'), [
    pytest.param(OLD_EMBEDDED, '修改TOML不会自动生效', id='builder-not-recreated'),
    pytest.param(False, '未内嵌buildkitd配置', id='builder-without-config'),
])
def test_build_script_requires_recreated_builder(tmp_path, embedded, message):
    """修改buildkit-p5.toml后未重建构建器时，在任何构建调用之前报错并提示重建。"""
    _fake_repo(tmp_path, embedded=embedded)
    code, out = _run_build(tmp_path, '-BuildAndExport',
                           '-ReuseVerifiedManifest', RUN_ID)
    assert code != 0 and message in out, out
    if embedded:
        assert f'mirrors={DAOCLOUD_MIRROR};' in out and 'rm --keep-state' in out
    assert not (tmp_path / 'bin' / 'calls.jsonl').exists()


@needs_windows_powershell
@pytest.mark.parametrize('arguments', [
    pytest.param(('-AptMirror', 'tuna'), id='mirror-without-build'),
    pytest.param(('-Probe', 'Arm64', '-ReuseVerifiedManifest',
                 RUN_ID, '-PipIndexUrl', TUNA_PYPI), id='mirror-with-probe'),
    pytest.param(('-BuildAndExport', '-ReuseVerifiedManifest', RUN_ID,
                 '-PipIndexUrl', 'http://pypi.example/simple'), id='http-pip'),
    pytest.param(('-ReuseBackendFrom', '20261012-213647-69609d73'),
                 id='backend-reuse-without-build'),
    pytest.param(('-BuildAndExport', '-ReuseVerifiedManifest', RUN_ID, '-ReuseBackendFrom', '20261012-213647-69609d73',
                  '-AptMirror', 'tuna'), id='backend-reuse-with-sources'),
    pytest.param(('-BuildAndExport', '-ReuseVerifiedManifest', RUN_ID, '-ReuseBackendFrom', '..\\other'),
                 id='backend-reuse-bad-run-id'),
])
def test_build_script_rejects_sources_before_creating_run(tmp_path, arguments):
    root, _ = _fake_repo(tmp_path)
    code, out = _run_build(tmp_path, *arguments)
    assert code != 0, out
    assert [path.name for path in root.iterdir()] == [RUN_ID]
    assert not (tmp_path / 'bin' / 'calls.jsonl').exists()


@needs_powershell
def test_manifest_reuse_rejects_source_outside_delivery_root(tmp_path):
    root, run, lock = _make_record(tmp_path)
    outside = tmp_path / 'elsewhere' / RUN_ID
    shutil.copytree(run, outside)
    status, out = _confirm(root, lock, source=outside)
    assert status == 2 and out.startswith('FAIL [REUSE-SOURCE]'), out
    status, out = _confirm(root, lock, source='20261012-000000-deadbeef')
    assert status == 2 and out.startswith('FAIL [REUSE-SOURCE]'), out


# ---------- 复用历史backend.tar：生成与BuildKit导出结构一致的小型OCI归档 ----------
BACKEND_RUN = '20261012-213647-69609d73'
DOCKERIGNORE = '**/__pycache__\n**/*.pyc\nvar\n'
# 与2026-10-12实际成功导出的后端一致：仅Debian主仓库与PyPI走清华。
BACKEND_ARGS = {'DEBIAN_MIRROR': TUNA_DEBIAN, 'DEBIAN_SECURITY_MIRROR': '', 'LIBREOFFICE_BASE_URL': '',
                'PYPI_INDEX_URL': TUNA_PYPI}


def _layer(files, prefix=''):
    """生成gzip层；返回(压缩内容, diff_id)。files为{路径: 内容}，目录项自动补齐。"""
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode='w', format=tarfile.PAX_FORMAT) as layer:
        folders = sorted(
            {'/'.join(path.split('/')[:n]) for path in files for n in range(1, path.count('/') + 1)})
        for folder in folders:
            info = tarfile.TarInfo(prefix + folder + '/')
            info.type = tarfile.DIRTYPE
            layer.addfile(info)
        for path, data in sorted(files.items()):
            info = tarfile.TarInfo(prefix + path)
            info.size = len(data)
            layer.addfile(info, io.BytesIO(data))
    raw = buffer.getvalue()
    return gzip.compress(raw, mtime=0), _sha(raw)


def _history(dockerfile_text, args):
    """按BuildKit记录格式生成本项目指令的history（格式已用真实导出的backend.tar核对）。"""
    module = _load_script_module(VERIFY_BACKEND, 'p5_verify_backend')
    values, declared, entries = {**args, 'TARGETARCH': 'arm64'}, [], []
    for step in module.dockerfile_steps(dockerfile_text):
        keyword = step.split(None, 1)[0]
        if keyword == 'ARG':
            name = step[4:].split('=', 1)[0]
            declared.append(name)
            entries.append(f'ARG {name}={values[name]}')
        elif keyword == 'RUN':
            pairs = [f'{name}={values[name]}' for name in declared]
            entries.append(
                f'RUN |{len(pairs)} {" ".join(pairs)} /bin/sh -c {module.run_command(step)} # buildkit')
        elif keyword == 'COPY':
            entries.append(f'{step} # buildkit')
        elif keyword == 'CMD':
            entries.append(
                'CMD [' + ' '.join(f'"{item}"' for item in json.loads(step[4:])) + ']')
        else:
            entries.append(step)
    return [{'created_by': 'base python layer'}] + [{'created_by': item} for item in entries]


def _workspace_sources(repo):
    files = {}
    for top in ('backend', 'scripts'):
        for path in sorted((repo / top).rglob('*')):
            relative = path.relative_to(repo).as_posix()
            if path.is_file() and '__pycache__' not in relative and not relative.endswith('.pyc'):
                files[relative] = path.read_bytes()
    return files


def _write_backend_run(repo, run_id=BACKEND_RUN, *, arch='arm64', sources_text=SAMPLE_SOURCES, tamper_layer=False,
                       history_edit=None, image_files=None):
    """在repo/var/p5-delivery下写一轮「后端导出成功、web失败」的记录；镜像内容取自当前工作区。"""
    lock = json.loads(
        (repo / 'deploy/p5-images.json').read_text(encoding='utf-8'))
    dockerfile_text = (
        repo / 'deploy/Dockerfile.backend').read_text(encoding='utf-8')
    files = image_files if image_files is not None else _workspace_sources(
        repo)
    base, base_id = _layer(
        {'etc/apt/sources.list.d/debian.sources': sources_text.encode('utf-8')})
    backend, backend_id = _layer(
        {'app/' + path: data for path, data in files.items() if path.startswith('backend/')}, './')
    scripts, scripts_id = _layer(
        {'app/' + path: data for path, data in files.items() if path.startswith('scripts/')})
    layers = [(base, base_id), (backend, backend_id), (scripts, scripts_id)]
    history = _history(dockerfile_text, BACKEND_ARGS)
    if history_edit:
        history = history_edit(history)
    config = json.dumps({'architecture': arch, 'os': 'linux', 'history': history,
                         'rootfs': {'type': 'layers', 'diff_ids': [item[1] for item in layers]}}).encode()
    manifest = json.dumps({'schemaVersion': 2, 'mediaType': 'application/vnd.oci.image.manifest.v1+json',
                           'config': {'digest': _sha(config), 'size': len(config)},
                           'layers': [{'mediaType': 'application/vnd.oci.image.layer.v1.tar+gzip',
                                       'digest': _sha(item[0]), 'size': len(item[0])} for item in layers]}).encode()
    blobs = {_sha(data): data for data in [
        config, manifest] + [item[0] for item in layers]}
    if tamper_layer:
        blobs[_sha(scripts)] = scripts[:-1] + bytes([scripts[-1] ^ 1])
    index = {'schemaVersion': 2, 'manifests': [{'mediaType': 'application/vnd.oci.image.manifest.v1+json',
                                                'digest': _sha(manifest), 'size': len(manifest),
                                                'platform': {'architecture': arch, 'os': 'linux'}}]}
    docker_manifest = [{'Config': 'blobs/sha256/' + _sha(config)[7:], 'RepoTags': [lock['outputs']['backend']],
                        'Layers': ['blobs/sha256/' + _sha(item[0])[7:] for item in layers]}]
    run = repo / 'var' / 'p5-delivery' / run_id
    run.mkdir(parents=True, exist_ok=True)
    with tarfile.open(run / 'backend.tar', 'w') as archive:
        entries = {'blobs/sha256/' +
                   digest[7:]: data for digest, data in blobs.items()}
        entries.update({'index.json': json.dumps(index).encode(), 'manifest.json': json.dumps(docker_manifest).encode(),
                        'oci-layout': b'{"imageLayoutVersion":"1.0.0"}'})
        for name, data in entries.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            archive.addfile(info, io.BytesIO(data))
    python_digest = lock['sources']['python'].split('@')[1]
    metadata = {'containerimage.digest': _sha(manifest), 'containerimage.config.digest': _sha(config),
                'image.name': 'docker.io/' + lock['outputs']['backend'],
                'buildx.build.provenance': {
                    'invocation': {'parameters': {'args': {
                        'build-arg:PYTHON_IMAGE': lock['sources']['python'],
                        **{f'build-arg:{name}': value for name, value in BACKEND_ARGS.items()}}}},
                    'materials': [{'uri': 'pkg:docker/python@3.12?platform=linux%2Farm64',
                                   'digest': {'sha256': python_digest[7:]}}]}}
    _write_ps_utf8(run / 'backend-metadata.json',
                   json.dumps(metadata, indent=2))
    record = {'apt_mirror': 'tuna', 'debian_uri': TUNA_DEBIAN, 'apt_security_mirror': 'official',
              'debian_security_uri': OFFICIAL_SECURITY, 'libreoffice_version': LIBREOFFICE_VERSION,
              'libreoffice_base_url': OFFICIAL_LIBREOFFICE, 'libreoffice_arm64_sha256': LIBREOFFICE_SUMS['arm64'],
              'pypi_index_url': TUNA_PYPI,
              'dockerfile_sha256': hashlib.sha256((repo / 'deploy/Dockerfile.backend').read_bytes()).hexdigest(),
              'apt_sources_sha256': hashlib.sha256((repo / 'deploy/apt-sources.sh').read_bytes()).hexdigest()}
    _write_ps_utf8(run / 'build-sources.json', json.dumps(record, indent=2))
    _write_ps_utf8(run / 'backend-build.log', '\n'.join(
        ['[sources] apt_mirror=tuna', f'#20 exporting manifest {_sha(manifest)} done', '#20 sending tarball 1.0s done']))
    _write_ps_utf8(run / 'web-build.log',
                   'ERROR: unexpected status from HEAD request: 502 Bad Gateway')
    _write_ps_utf8(run / 'builder.json', json.dumps(
        {'Name': 'policy-p5-arm64', 'Driver': 'docker-container', 'Nodes': [{'Version': 'v0.21.0'}]}))
    shutil.copy2(repo / 'deploy/p5-images.json', run / 'source-lock.json')
    return run


def _backend_repo(tmp_path):
    """独立校验器用的最小仓库：真实Dockerfile与锁文件，少量后端源码与脚本。"""
    repo = tmp_path / 'repo'
    for relative in ('deploy/Dockerfile.backend', 'deploy/apt-sources.sh', 'deploy/p5-images.json',
                     'scripts/build-p5-arm64.ps1', 'scripts/p5-build-sources.ps1'):
        (repo / relative).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / relative, repo / relative)
    (repo / '.dockerignore').write_text(DOCKERIGNORE, encoding='utf-8')
    for relative, text in {'backend/requirements.txt': 'fastapi\n', 'backend/app/main.py': 'app = None\n',
                           'backend/.env.example': 'A=1\n', 'scripts/run-service.py': 'print(1)\n'}.items():
        (repo / relative).parent.mkdir(parents=True, exist_ok=True)
        (repo / relative).write_text(text, encoding='utf-8')
    # 被.dockerignore排除的文件不在镜像内，也不得视为差异。
    (repo / 'backend/app/__pycache__').mkdir()
    (repo / 'backend/app/__pycache__/main.cpython-312.pyc').write_bytes(b'\x00')
    return repo


def _verify(repo, *arguments):
    module = _load_script_module(VERIFY_BACKEND, 'p5_verify_backend')
    return module.main(['--root', str(repo), '--source', BACKEND_RUN, *arguments])


def test_backend_reuse_verify_only_passes_and_records_tooling(tmp_path, capsys):
    repo = _backend_repo(tmp_path)
    _write_backend_run(repo)
    # 宿主机P5工具在镜像导出后变更：允许，但必须逐个记录。
    (repo / 'scripts/build-p5-arm64.ps1').write_bytes((repo /
                                                       'scripts/build-p5-arm64.ps1').read_bytes() + b'\r\n')
    (repo / 'scripts/p5-new-tool.py').write_text('print(2)\n', encoding='utf-8')
    report = tmp_path / 'report.json'
    assert _verify(repo, '--verify-only', '--output',
                   str(report)) == 0, capsys.readouterr().out
    data = json.loads(report.read_text(encoding='utf-8'))
    assert data['result'] == 'PASS' and data['mode'] == 'verify-only' and data['layers'] == 3
    assert {item['path'] for item in data['allowed_tooling_differences']} == {
        'scripts/build-p5-arm64.ps1', 'scripts/p5-new-tool.py'}
    assert data['build_args'] == {'PYTHON_IMAGE': PYTHON_IMAGE, **BACKEND_ARGS}
    assert data['notes'] == []
    # 只读：交付根目录下没有新增任何运行目录或报告。
    assert [path.name for path in (
        repo / 'var/p5-delivery').iterdir()] == [BACKEND_RUN]
    assert not (repo / 'var/p5-delivery' / BACKEND_RUN /
                'backend-reuse.json').exists()
    # 报告不得写进交付根目录。
    assert _verify(repo, '--verify-only', '--output',
                   str(repo / 'var/p5-delivery/x.json')) == 2


def test_backend_reuse_copies_only_after_verification(tmp_path):
    repo = _backend_repo(tmp_path)
    source = _write_backend_run(repo)
    dest = repo / 'var/p5-delivery/20261013-090000-0000abcd'
    dest.mkdir()
    assert _verify(repo, '--dest', str(dest)) == 0
    assert (dest / 'backend.tar').read_bytes() == (source /
                                                   'backend.tar').read_bytes()
    assert not (dest / 'backend.tar.partial').exists()
    report = json.loads(
        (dest / 'backend-reuse.json').read_text(encoding='utf-8'))
    assert report['result'] == 'PASS' and report['source_run'] == BACKEND_RUN
    assert report['backend_tar_sha256'] == hashlib.sha256(
        (source / 'backend.tar').read_bytes()).hexdigest()
    for name in ('backend-build.log', 'builder.json', 'source-lock.json'):
        assert (dest / 'reused-backend' /
                name).read_bytes() == (source / name).read_bytes()
    assert (dest / 'build-sources.json').read_bytes() == (source /
                                                          'build-sources.json').read_bytes()
    # 已有backend.tar时拒绝覆盖；复用而来的轮次不能再作为来源（链式复用的错误码见拒绝用例）。
    assert _verify(repo, '--dest', str(dest)) == 2
    other = repo / 'var/p5-delivery/20261013-100000-0000abce'
    other.mkdir()
    (dest / 'web-build.log').write_text('x', encoding='utf-8')
    assert _verify(repo, '--source', dest.name, '--dest', str(other)) == 2
    assert not (other / 'backend.tar').exists() and not (other /
                                                         'backend.tar.partial').exists()


def _edit_file(relative, transform):
    def mutate(repo, run):
        path = repo / relative
        path.write_text(transform(path.read_text(
            encoding='utf-8-sig')), encoding='utf-8')
    return mutate


def _edit_json(name, transform):
    def mutate(repo, run):
        data = json.loads((run / name).read_text(encoding='utf-8-sig'))
        transform(data)
        _write_ps_utf8(run / name, json.dumps(data, indent=2))
    return mutate


def _rebuild(**options):
    return lambda repo, run: _write_backend_run(repo, **options)


def _swap_history(history):
    history[-1], history[-2] = history[-2], history[-1]
    return history


def _tuna_history(history):
    return [{'created_by': item['created_by'].replace(TUNA_PYPI, 'https://pypi.example/simple')} for item in history]


@pytest.mark.parametrize(('mutate', 'code'), [
    pytest.param(_edit_file('backend/app/main.py', lambda text: text + '# changed\n'), 'REUSE-BACKEND-CONTENT',
                 id='runtime-source-changed'),
    pytest.param(lambda repo, run: (repo / 'backend/new_module.py').write_text('x\n', encoding='utf-8'),
                 'REUSE-BACKEND-CONTENT', id='runtime-source-added'),
    pytest.param(_edit_file('deploy/Dockerfile.backend', lambda text: text.replace('--retries 5', '--retries 6')),
                 'REUSE-BACKEND-CONFIG', id='dockerfile-changed'),
    pytest.param(_edit_file('deploy/apt-sources.sh', lambda text: text + '\n# changed\n'), 'REUSE-BACKEND-CONFIG',
                 id='apt-script-changed'),
    pytest.param(_edit_json('source-lock.json', lambda data: data['sources'].update(node='node@sha256:' + '0' * 64)),
                 'REUSE-BACKEND-LOCK', id='lock-changed'),
    pytest.param(_edit_json('backend-metadata.json', lambda data: data['buildx.build.provenance']['invocation']
                            ['parameters']['args'].update({'build-arg:PYPI_INDEX_URL': ''})),
                 'REUSE-BACKEND-CONFIG', id='metadata-args-differ'),
    pytest.param(_edit_json('backend-metadata.json', lambda data: data.update({'containerimage.digest': _sha(b'x')})),
                 'REUSE-BACKEND-NOT-SUCCESS', id='metadata-digest-not-exported'),
    pytest.param(lambda repo, run: (run / 'web-build.log').unlink(), 'REUSE-BACKEND-NOT-SUCCESS',
                 id='backend-command-not-finished'),
    pytest.param(lambda repo, run: (run / 'backend-build.log').write_text('ERROR: failed\n', encoding='utf-8'),
                 'REUSE-BACKEND-NOT-SUCCESS', id='backend-build-failed'),
    pytest.param(lambda repo, run: (run / 'builder.json').unlink(),
                 'REUSE-BACKEND-INCOMPLETE', id='missing-builder'),
    pytest.param(lambda repo, run: (run / 'backend-reuse.json').write_text('{}', encoding='utf-8'),
                 'REUSE-BACKEND-SOURCE', id='chained-reuse'),
    pytest.param(_rebuild(tamper_layer=True),
                 'REUSE-BACKEND-TAR', id='layer-blob-tampered'),
    pytest.param(_rebuild(arch='amd64'), 'REUSE-BACKEND-ARCH', id='not-arm64'),
    pytest.param(_rebuild(history_edit=_swap_history),
                 'REUSE-BACKEND-HISTORY', id='history-order'),
    pytest.param(_rebuild(history_edit=_tuna_history),
                 'REUSE-BACKEND-HISTORY', id='history-args'),
    pytest.param(_rebuild(sources_text=SAMPLE_SOURCES.replace(OFFICIAL_DEBIAN, TUNA_DEBIAN)), 'REUSE-BACKEND-CONTENT',
                 id='debian-sources-not-restored'),
])
def test_backend_reuse_rejects_unprovable_source(tmp_path, mutate, code):
    repo = _backend_repo(tmp_path)
    run = _write_backend_run(repo)
    mutate(repo, run)
    dest = repo / 'var/p5-delivery/20261013-090000-0000abcd'
    dest.mkdir()
    assert _verify(repo, '--dest', str(dest)) == 2
    report = json.loads(
        (dest / 'backend-reuse.json').read_text(encoding='utf-8'))
    assert report['result'] == 'FAIL' and report['code'] == code, report
    # 失败时本轮不留下任何归档。
    assert not (dest / 'backend.tar').exists() and not (dest /
                                                        'backend.tar.partial').exists()


@needs_windows_powershell
def test_build_script_reuses_verified_backend(tmp_path):
    """端到端：-ReuseBackendFrom经校验器复用后端，只构建web与两个基础镜像归档。"""
    root, lock = _fake_repo(tmp_path)
    source = _write_backend_run(tmp_path)
    code, out = _run_build(tmp_path, '-BuildAndExport', '-ReuseVerifiedManifest', RUN_ID,
                           '-ReuseBackendFrom', BACKEND_RUN, '-PythonExe', sys.executable)
    assert code == 0, out
    dest = next(path for path in root.iterdir()
                if path.name not in (RUN_ID, BACKEND_RUN))
    calls = [json.loads(line) for line in (
        tmp_path / 'bin' / 'calls.jsonl').read_text(encoding='utf-8').splitlines()]
    assert len(calls) == 3 and not any(
        'deploy/Dockerfile.backend' in call for call in calls)
    assert (dest / 'backend.tar').read_bytes() == (source /
                                                   'backend.tar').read_bytes()
    completed = json.loads(
        (dest / 'completed.json').read_text(encoding='utf-8-sig'))
    assert completed['backend_mode'] == 'reused' and completed['backend_source'] == BACKEND_RUN
    assert completed['build_sources'] == json.loads(
        (source / 'build-sources.json').read_text(encoding='utf-8-sig'))
    checksums = json.loads(
        (dest / 'checksums.json').read_text(encoding='utf-8-sig'))
    checksums = checksums if isinstance(checksums, list) else [checksums]
    assert {'File': 'backend.tar', 'Hash': hashlib.sha256(
        (source / 'backend.tar').read_bytes()).hexdigest().upper()} in checksums
    log = (dest / 'backend-reuse.log').read_text(encoding='utf-8-sig')
    assert log.startswith(
        'PASS 复用' + BACKEND_RUN) and 'RemoteException' not in log


@needs_windows_powershell
def test_build_script_stops_when_backend_reuse_fails(tmp_path):
    root, _ = _fake_repo(tmp_path)
    _write_backend_run(tmp_path)
    (tmp_path / 'scripts' / 'run-service.py').write_text('print(3)\n', encoding='utf-8')
    code, out = _run_build(tmp_path, '-BuildAndExport', '-ReuseVerifiedManifest', RUN_ID,
                           '-ReuseBackendFrom', BACKEND_RUN, '-PythonExe', sys.executable)
    assert code != 0 and 'REUSE-BACKEND-CONTENT' in out, out
    dest = next(path for path in root.iterdir()
                if path.name not in (RUN_ID, BACKEND_RUN))
    assert not (dest / 'backend.tar').exists() and not (dest /
                                                        'completed.json').exists()
    assert not (tmp_path / 'bin' / 'calls.jsonl').exists()

"""文件说明：P5正式构建复用历史backend.tar前的本地严格校验；不联网、不调用Docker、不加载镜像。

只有同时满足以下各项，才把历史轮次的后端归档复制进本轮交付目录并判定PASS：
  1. 来源：位于交付根目录内、由该轮亲自构建（非复用的复用），构建日志含导出完成记录，且后续web步骤已开始；
  2. 配置：source-lock.json与当前锁文件逐字节一致；Dockerfile.backend摘要、LibreOffice版本与SHA256与当前一致；
     元数据中的构建参数、基础镜像来源与build-sources.json一致；
  3. 归档：每个blob按内容摘要校验，清单/配置摘要与元数据一致，架构linux/arm64，每层解压后摘要等于diff_id；
  4. 历史：镜像配置history中本项目各指令与当前Dockerfile.backend逐条一致；
  5. 内容：镜像内/app/backend、/app/scripts与当前工作区（按.dockerignore过滤）逐文件一致；
     仅P5宿主机构建工具（固定清单，不在容器内运行）允许不同，并逐个记录两侧摘要；
     最终镜像的Debian源配置已恢复为官方源。
先在来源目录只读校验并记录整个backend.tar的sha256，再以.partial临时名复制，复制件摘要一致后才改名为backend.tar；
校验失败时不会在本轮目录留下backend.tar。--verify-only只做只读校验，不复制。无论成败都写报告；失败返回码2。
"""
import argparse
import fnmatch
import gzip
import hashlib
import json
import os
import re
import shutil
import sys
import tarfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
RUN_PATTERN = re.compile(r'^\d{8}-\d{6}-[a-f0-9]{8}$')
# 仅宿主机执行的P5构建工具与其测试；镜像内存在但运行时不使用，差异须记录不得静默忽略。
TOOLING_PATTERNS = ('scripts/build-p5-arm64.ps1', 'scripts/p5-*', 'backend/tests/test_compose_p5.py',
                    'backend/tests/p5_build/*')
COPY_ROOTS = {'app/backend/': 'backend/', 'app/scripts/': 'scripts/'}
OFFICIAL_URIS = ['URIs: http://deb.debian.org/debian',
                 'URIs: http://deb.debian.org/debian-security']
OFFICIAL = {'debian': 'http://deb.debian.org/debian', 'security': 'http://deb.debian.org/debian-security',
            'libreoffice': 'https://downloadarchive.documentfoundation.org/libreoffice/old',
            'pypi': 'https://pypi.org/simple'}
CHUNK = 1024 * 1024


class ReuseError(Exception):
    """带错误代码的校验失败，代码用于报告与测试定位。"""

    def __init__(self, code, message):
        super().__init__(f'[{code}] {message}')
        self.code = code


def require(condition, code, message):
    if not condition:
        raise ReuseError(code, message)


def file_sha256(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as handle:
        for block in iter(lambda: handle.read(CHUNK), b''):
            digest.update(block)
    return digest.hexdigest()


def read_json(path, code):
    try:
        return json.loads(Path(path).read_text(encoding='utf-8-sig'))
    except (OSError, ValueError) as error:
        raise ReuseError(code, f'无法读取JSON：{Path(path).name}：{error}') from None


# ---------- .dockerignore匹配（与moby/patternmatcher语义一致：路径或其任一父目录命中即排除，后规则优先） ----------
def _pattern_regex(pattern):
    out, i = '', 0
    while i < len(pattern):
        char = pattern[i]
        if char == '*':
            if pattern[i + 1:i + 2] == '*':
                i += 1
                if pattern[i + 1:i + 2] == '/':
                    i += 1
                    out += '(.*/)?'
                else:
                    out += '.*'
            else:
                out += '[^/]*'
        elif char == '?':
            out += '[^/]'
        elif char == '\\' and i + 1 < len(pattern):
            i += 1
            out += re.escape(pattern[i])
        elif char == '[':
            end = pattern.find(']', i + 1)
            if end == -1:
                out += re.escape(char)
            else:
                out += pattern[i:end + 1]
                i = end
        else:
            out += re.escape(char)
        i += 1
    return re.compile('^' + out + '$')


def load_dockerignore(path):
    rules = []
    for raw in Path(path).read_text(encoding='utf-8-sig').splitlines():
        line = raw.strip()
        if not line or line.startswith('#'):
            continue
        negate = line.startswith('!')
        line = line[1:].strip() if negate else line
        line = str(PurePosixPath('/' + line))[1:] or '.'
        rules.append((negate, _pattern_regex(line)))
    return rules


def ignored(rules, relative):
    parts = relative.split('/')
    candidates = ['/'.join(parts[:n]) for n in range(1, len(parts) + 1)]
    result = False
    for negate, regex in rules:
        if any(regex.match(item) for item in candidates):
            result = not negate
    return result


def workspace_files(root, rules):
    """按.dockerignore过滤后返回backend/与scripts/下全部普通文件的sha256。"""
    files = {}
    for top in COPY_ROOTS.values():
        base = root / top.rstrip('/')
        for folder, dirs, names in os.walk(base):
            rel_dir = Path(folder).relative_to(root).as_posix()
            dirs[:] = [d for d in dirs if not ignored(rules, f'{rel_dir}/{d}')]
            for name in names:
                relative = f'{rel_dir}/{name}'
                if not ignored(rules, relative):
                    files[relative] = file_sha256(root / relative)
    return files


# ---------- Dockerfile解析 ----------
def dockerfile_steps(text):
    """返回最后一个FROM之后的指令列表；去掉续行符，与BuildKit记录的原文一致。"""
    joined = text.replace('\\\n', '')
    steps = [line.strip() for line in joined.splitlines()
             if line.strip() and not line.lstrip().startswith('#')]
    froms = [i for i, step in enumerate(steps) if step.startswith('FROM ')]
    require(froms, 'REUSE-BACKEND-CONFIG', 'Dockerfile.backend缺少FROM')
    return steps[froms[-1] + 1:]


def run_command(step):
    """去掉RUN后的--mount等选项，得到/bin/sh -c执行的命令原文。"""
    rest = step[4:].lstrip()
    while rest.startswith('--'):
        rest = rest.split(None, 1)[1] if ' ' in rest else ''
        rest = rest.lstrip()
    return rest


def history_matches(step, created):
    keyword = step.split(None, 1)[0]
    if keyword == 'RUN':
        return created.startswith('RUN ') and created.endswith(f'/bin/sh -c {run_command(step)} # buildkit')
    if keyword == 'ARG':
        return created.split('=', 1)[0] == step.split('=', 1)[0]
    if keyword == 'CMD':
        return json.loads(step[4:]) == re.findall(r'"([^"]*)"', created[4:])
    if keyword == 'COPY':
        return created == f'{step} # buildkit'
    return created.split() == step.split()


def run_args(created):
    """解析history中RUN |N K=V ...的构建参数。"""
    match = re.match(r'^RUN \|(\d+) (.*?) /bin/sh -c ', created)
    if not match:
        return {}
    tokens = match.group(2).split(' ')
    require(len(tokens) == int(match.group(1)),
            'REUSE-BACKEND-HISTORY', f'无法解析构建参数：{created[:120]}')
    return dict(token.split('=', 1) for token in tokens)


# ---------- 归档校验 ----------
class HashingReader:
    """包装文件对象，边读边计算sha256；用于在一次解压中同时得到diff_id与层内文件。"""

    def __init__(self, raw):
        self.raw, self.digest = raw, hashlib.sha256()

    def read(self, size=-1):
        data = self.raw.read(size)
        self.digest.update(data)
        return data

    def drain(self):
        while self.read(CHUNK):
            pass
        return 'sha256:' + self.digest.hexdigest()


def scan_layer(blob, image_files, state):
    """流式读取一层：返回解压后摘要，并把/app下文件与Debian源配置合并进state（后层覆盖前层）。"""
    head = blob.read(2)
    blob.seek(0)
    stream = gzip.GzipFile(fileobj=blob) if head == b'\x1f\x8b' else blob
    reader = HashingReader(stream)
    with tarfile.open(fileobj=reader, mode='r|') as layer:
        for member in layer:
            # 只去掉“./”前缀，保留以点开头的文件名（如.env.example）。
            name = member.name[2:] if member.name.startswith(
                './') else member.name
            name = name.lstrip('/')
            base = PurePosixPath(name).name
            if base.startswith('.wh.'):
                target = str(PurePosixPath(name).parent / base[4:])
                if any(target.startswith(prefix) or (target + '/').startswith(prefix) for prefix in COPY_ROOTS):
                    state['whiteouts'].append(name)
                continue
            if name.startswith('etc/apt/sources.list.d/'):
                state['apt_files'].add(name)
                if name == 'etc/apt/sources.list.d/debian.sources' and member.isfile():
                    state['debian_sources'] = layer.extractfile(
                        member).read().decode('utf-8', 'replace')
            for prefix, workspace in COPY_ROOTS.items():
                if name.startswith(prefix) and member.isfile():
                    digest = hashlib.sha256()
                    handle = layer.extractfile(member)
                    for block in iter(lambda: handle.read(CHUNK), b''):
                        digest.update(block)
                    image_files[workspace +
                                name[len(prefix):]] = digest.hexdigest()
                elif name.startswith(prefix) and not member.isdir():
                    state['special'].append(name)
    return reader.drain()


def verify_archive(tar_path, metadata, lock):
    """逐blob按摘要校验，核对清单、配置、架构与每层diff_id，并收集镜像内文件。"""
    image_files = {}
    state = {'whiteouts': [], 'special': [],
             'apt_files': set(), 'debian_sources': None}
    try:
        archive = tarfile.open(tar_path, mode='r:')
        members = {member.name: member for member in archive.getmembers()}
    except (OSError, tarfile.TarError) as error:
        raise ReuseError('REUSE-BACKEND-TAR', f'归档无法完整读取：{error}') from None
    with archive:
        def blob(digest):
            name = 'blobs/sha256/' + digest.split(':', 1)[1]
            require(name in members, 'REUSE-BACKEND-TAR', f'归档缺少{name}')
            return archive.extractfile(members[name])

        for name, member in members.items():
            if name.startswith('blobs/sha256/') and member.isfile():
                digest = hashlib.sha256()
                handle = archive.extractfile(member)
                for block in iter(lambda: handle.read(CHUNK), b''):
                    digest.update(block)
                require(digest.hexdigest() == name.rsplit('/', 1)
                        [1], 'REUSE-BACKEND-TAR', f'{name}内容与摘要不符')
        for required in ('index.json', 'manifest.json', 'oci-layout'):
            require(required in members,
                    'REUSE-BACKEND-TAR', f'归档缺少{required}')
        index = json.load(archive.extractfile(members['index.json']))
        descriptors = index.get('manifests', [])
        require(len(descriptors) == 1, 'REUSE-BACKEND-TAR',
                f'index.json应只含一个镜像，实际{len(descriptors)}')
        descriptor = descriptors[0]
        require(descriptor['digest'] == metadata['containerimage.digest'], 'REUSE-BACKEND-TAR',
                '归档镜像摘要与backend-metadata.json不一致')
        require(descriptor.get('platform') == {'architecture': 'arm64', 'os': 'linux'}, 'REUSE-BACKEND-ARCH',
                f"归档平台为{descriptor.get('platform')}")
        manifest = json.load(blob(descriptor['digest']))
        require(manifest['config']['digest'] == metadata['containerimage.config.digest'], 'REUSE-BACKEND-TAR',
                '配置摘要与元数据不一致')
        docker_manifest = json.load(
            archive.extractfile(members['manifest.json']))
        require(len(docker_manifest) == 1 and docker_manifest[0].get('RepoTags') == [lock['outputs']['backend']],
                'REUSE-BACKEND-TAR', f"镜像标签应为{lock['outputs']['backend']}")
        config = json.load(blob(manifest['config']['digest']))
        require(config.get('architecture') == 'arm64' and config.get('os') == 'linux', 'REUSE-BACKEND-ARCH',
                f"镜像配置架构为{config.get('os')}/{config.get('architecture')}")
        diff_ids = config['rootfs']['diff_ids']
        layers = manifest['layers']
        require(len(diff_ids) == len(layers),
                'REUSE-BACKEND-TAR', '层数量与diff_id数量不一致')
        require(docker_manifest[0]['Layers'] == ['blobs/sha256/' + item['digest'].split(':', 1)[1] for item in layers],
                'REUSE-BACKEND-TAR', 'manifest.json层列表与OCI清单不一致')
        for layer, diff_id in zip(layers, diff_ids):
            require(members['blobs/sha256/' + layer['digest'].split(':', 1)[1]].size == layer['size'],
                    'REUSE-BACKEND-TAR', f"{layer['digest']}长度与清单不一致")
            actual = scan_layer(blob(layer['digest']), image_files, state)
            require(actual == diff_id, 'REUSE-BACKEND-TAR',
                    f"{layer['digest']}解压后摘要{actual}不等于diff_id {diff_id}")
    return {'manifest_digest': descriptor['digest'], 'config_digest': manifest['config']['digest'],
            'layers': len(layers), 'diff_ids': diff_ids, 'config': config}, image_files, state


# ---------- 主流程 ----------
def resolve_source(value, delivery_root):
    root = delivery_root.resolve()
    candidate = (root / value) if RUN_PATTERN.match(value) else Path(value)
    candidate = (candidate if candidate.is_absolute()
                 else Path.cwd() / candidate).resolve()
    require(candidate.parent == root, 'REUSE-BACKEND-SOURCE',
            f'来源须为{root}下的运行目录：{candidate}')
    require(RUN_PATTERN.match(candidate.name) and candidate.is_dir(),
            'REUSE-BACKEND-SOURCE', f'来源目录不存在：{candidate}')
    return candidate


def check_source_run(source, builder):
    """来源轮次须亲自完成后端导出；复用而来的归档不能再被复用。"""
    required = ('backend.tar', 'backend-metadata.json', 'build-sources.json', 'backend-build.log',
                'source-lock.json', 'builder.json')
    missing = [name for name in required if not (source / name).is_file()]
    require(not missing, 'REUSE-BACKEND-INCOMPLETE', f'来源缺少{missing}')
    require(not (source / 'backend-reuse.json').exists(),
            'REUSE-BACKEND-SOURCE', '来源本身是复用轮次，须使用亲自构建后端的轮次')
    require((source / 'backend.tar').stat().st_size > 0,
            'REUSE-BACKEND-INCOMPLETE', 'backend.tar为空')
    info = read_json(source / 'builder.json', 'REUSE-BACKEND-SOURCE')
    nodes = info.get('Nodes') or []
    require(info.get('Name') == builder and info.get('Driver') == 'docker-container' and len(nodes) == 1
            and nodes[0].get('Version') == 'v0.21.0', 'REUSE-BACKEND-SOURCE', '来源轮次不是专用构建器policy-p5-arm64（BuildKit v0.21.0）')
    metadata = read_json(source / 'backend-metadata.json',
                         'REUSE-BACKEND-INCOMPLETE')
    log = (source / 'backend-build.log').read_text(encoding='utf-8-sig',
                                                   errors='replace')
    digest = metadata.get('containerimage.digest', '')
    require(f'exporting manifest {digest} done' in log and 'sending tarball' in log and 'ERROR:' not in log,
            'REUSE-BACKEND-NOT-SUCCESS', '构建日志缺少与元数据一致的导出完成记录或含ERROR')
    # 构建脚本逐步执行且任一步失败即中止：后端之后的步骤已开始，说明后端导出命令以0退出。
    require((source / 'web-build.log').exists() or (source / 'completed.json').exists(), 'REUSE-BACKEND-NOT-SUCCESS',
            '来源轮次未进入后端之后的步骤，无法证明后端导出命令成功结束')
    return metadata


def expected_args(record, lock):
    def value(key, official):
        return '' if record[key] == official else record[key]
    return {'PYTHON_IMAGE': lock['sources']['python'],
            'DEBIAN_MIRROR': value('debian_uri', OFFICIAL['debian']),
            'DEBIAN_SECURITY_MIRROR': value('debian_security_uri', OFFICIAL['security']),
            'LIBREOFFICE_BASE_URL': value('libreoffice_base_url', OFFICIAL['libreoffice']),
            'PYPI_INDEX_URL': value('pypi_index_url', OFFICIAL['pypi'])}


def check_config(source, metadata, root, lock_path, lock, notes):
    require(file_sha256(source / 'source-lock.json') == file_sha256(lock_path), 'REUSE-BACKEND-LOCK',
            '来源轮次的锁文件与当前deploy/p5-images.json不一致')
    record = read_json(source / 'build-sources.json',
                       'REUSE-BACKEND-INCOMPLETE')
    dockerfile = root / 'deploy/Dockerfile.backend'
    text = dockerfile.read_text(encoding='utf-8')
    require(record.get('dockerfile_sha256') == file_sha256(dockerfile), 'REUSE-BACKEND-CONFIG',
            '来源构建时的Dockerfile.backend与当前不一致')
    arm_sum = re.search(
        r'arm64\) dir=aarch64; pkg=aarch64; sum=([a-f0-9]{64})', text).group(1)
    version = re.search(r'version=([0-9.]+);', text).group(1)
    require(record.get('libreoffice_version') == version and record.get('libreoffice_arm64_sha256') == arm_sum,
            'REUSE-BACKEND-CONFIG', 'LibreOffice版本或SHA256与当前Dockerfile不一致')
    apt_hash = file_sha256(root / 'deploy/apt-sources.sh')
    if 'apt_sources_sha256' in record:
        require(record['apt_sources_sha256'] == apt_hash,
                'REUSE-BACKEND-CONFIG', 'apt-sources.sh与来源构建时不一致')
    else:
        notes.append('来源记录早于apt-sources.sh摘要登记；以镜像内Debian源已恢复为官方作为替代证据')
    args = metadata['buildx.build.provenance']['invocation']['parameters']['args']
    actual = {key.split(':', 1)[1]: value for key, value in args.items(
    ) if key.startswith('build-arg:')}
    expected = expected_args(record, lock)
    require(actual == expected, 'REUSE-BACKEND-CONFIG',
            f'元数据构建参数{actual}与build-sources.json推导值{expected}不一致')
    python_digest = lock['sources']['python'].split('@', 1)[1]
    materials = metadata['buildx.build.provenance'].get('materials', [])
    require(len(materials) == 1 and materials[0]['digest'].get('sha256') == python_digest.split(':', 1)[1]
            and 'platform=linux%2Farm64' in materials[0]['uri'], 'REUSE-BACKEND-CONFIG', '基础镜像来源与锁定Python摘要不一致')
    require(metadata.get('image.name') == 'docker.io/' +
            lock['outputs']['backend'], 'REUSE-BACKEND-CONFIG', '元数据镜像名与锁文件输出标签不一致')
    return record, text, expected


def check_history(config, dockerfile_text, expected):
    steps = dockerfile_steps(dockerfile_text)
    history = config.get('history', [])
    require(len(history) >= len(steps), 'REUSE-BACKEND-HISTORY',
            '镜像history条目少于Dockerfile指令')
    ours = history[-len(steps):]
    for step, entry in zip(steps, ours):
        created = entry.get('created_by', '')
        require(history_matches(step, created), 'REUSE-BACKEND-HISTORY',
                f'指令不一致：Dockerfile「{step[:80]}」 镜像「{created[:80]}」')
        if created.startswith('ARG ') and '=' in created:
            name, value = created[4:].split('=', 1)
            if name in expected:
                require(value == expected[name], 'REUSE-BACKEND-HISTORY',
                        f'history中ARG {name}={value}与记录{expected[name]}不一致')
        for name, value in run_args(created).items():
            if name in expected:
                require(value == expected[name], 'REUSE-BACKEND-HISTORY',
                        f'history中{name}={value}与记录{expected[name]}不一致')
    return len(steps)


def check_content(image_files, state, workspace):
    require(not state['whiteouts'] and not state['special'], 'REUSE-BACKEND-CONTENT',
            f"/app下存在删除标记或非普通文件：{(state['whiteouts'] + state['special'])[:5]}")
    sources = state['debian_sources'] or ''
    uris = [line for line in sources.splitlines() if line.startswith('URIs:')]
    require(uris == OFFICIAL_URIS, 'REUSE-BACKEND-CONTENT',
            f'镜像内Debian源未恢复为官方：{uris}')
    require(state['apt_files'] == {'etc/apt/sources.list.d/debian.sources'}, 'REUSE-BACKEND-CONTENT',
            f"镜像内存在多余的apt源文件：{sorted(state['apt_files'])}")
    allowed, rejected = [], []
    for path in sorted(set(image_files) | set(workspace)):
        image, current = image_files.get(path), workspace.get(path)
        if image == current:
            continue
        entry = {'path': path, 'image_sha256': image,
                 'workspace_sha256': current}
        (allowed if any(fnmatch.fnmatchcase(path, pattern)
         for pattern in TOOLING_PATTERNS) else rejected).append(entry)
    require(not rejected, 'REUSE-BACKEND-CONTENT',
            f'镜像内源码与当前工作区不一致（{len(rejected)}个）：' + '，'.join(item['path'] for item in rejected[:8]))
    return allowed


def main(argv=None):
    parser = argparse.ArgumentParser(description='复用历史backend.tar前的本地严格校验')
    parser.add_argument('--source', required=True,
                        help='运行编号或var/p5-delivery下的运行目录')
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument('--dest', help='本轮交付目录；校验通过后复制到此')
    target.add_argument('--verify-only', action='store_true',
                        help='只读校验来源，不复制、不写交付目录')
    parser.add_argument('--output', default='',
                        help='--verify-only时的JSON报告路径（须在交付根目录之外）')
    parser.add_argument('--root', default=str(ROOT))
    parser.add_argument('--delivery-root', default='var/p5-delivery')
    parser.add_argument('--builder', default='policy-p5-arm64')
    args = parser.parse_args(argv)
    root = Path(args.root).resolve()
    delivery_root = Path(args.delivery_root)
    delivery_root = (delivery_root if delivery_root.is_absolute()
                     else root / delivery_root).resolve()
    dest = Path(args.dest).resolve() if args.dest else None
    lock_path = root / 'deploy/p5-images.json'
    report = {'checked_at_utc': datetime.now(timezone.utc).isoformat(), 'result': 'FAIL', 'source_input': args.source,
              'mode': 'verify-only' if args.verify_only else 'copy'}
    try:
        if dest is not None:
            require(dest.parent == delivery_root and dest.is_dir(),
                    'REUSE-BACKEND-SOURCE', f'本轮目录须在{delivery_root}下')
            require(not (dest / 'backend.tar').exists(),
                    'REUSE-BACKEND-SOURCE', '本轮目录已有backend.tar，拒绝覆盖')
        source = resolve_source(args.source, delivery_root)
        require(source != dest, 'REUSE-BACKEND-SOURCE', '来源不能是本轮目录')
        report['source_run'] = source.name
        lock = read_json(lock_path, 'REUSE-BACKEND-LOCK')
        metadata = check_source_run(source, args.builder)
        notes = []
        record, dockerfile_text, expected = check_config(
            source, metadata, root, lock_path, lock, notes)
        # 先整体摘要，再逐blob/逐层只读校验来源归档；复制件须与此摘要一致，校验对象即交付对象。
        tar_sha = file_sha256(source / 'backend.tar')
        archive, image_files, state = verify_archive(
            source / 'backend.tar', metadata, lock)
        own_steps = check_history(archive.pop(
            'config'), dockerfile_text, expected)
        workspace = workspace_files(
            root, load_dockerignore(root / '.dockerignore'))
        allowed = check_content(image_files, state, workspace)
        if dest is not None:
            copy_dir = dest / 'reused-backend'
            copy_dir.mkdir(exist_ok=True)
            for name in ('backend-build.log', 'builder.json', 'source-lock.json'):
                shutil.copyfile(source / name, copy_dir / name)
            partial = dest / 'backend.tar.partial'
            shutil.copyfile(source / 'backend.tar', partial)
            require(file_sha256(partial) == tar_sha, 'REUSE-BACKEND-TAR',
                    '复制后的backend.tar.partial与已校验的来源摘要不一致')
            shutil.copyfile(source / 'backend-metadata.json',
                            dest / 'backend-metadata.json')
            shutil.copyfile(source / 'build-sources.json',
                            dest / 'build-sources.json')
            os.replace(partial, dest / 'backend.tar')
        report.update(result='PASS', source_run=source.name, backend_tar_sha256=tar_sha,
                      backend_tar_bytes=(
                          source / 'backend.tar').stat().st_size, manifest_digest=archive['manifest_digest'],
                      config_digest=archive['config_digest'], layers=archive['layers'], dockerfile_steps=own_steps,
                      build_sources=record, build_args=expected, image_source_files=len(
                          image_files),
                      workspace_source_files=len(workspace), tooling_patterns=list(TOOLING_PATTERNS),
                      allowed_tooling_differences=allowed, notes=notes)
        action = '只读校验' if dest is None else '复用'
        print(f"PASS {action}{source.name}的backend.tar：{archive['layers']}层逐层校验通过，"
              f"源码{len(image_files)}个文件一致，构建工具差异{len(allowed)}个已记录")
        for item in allowed:
            print(
                f"  工具差异 {item['path']} 镜像={str(item['image_sha256'])[:12]} 当前={str(item['workspace_sha256'])[:12]}")
        code = 0
    except ReuseError as error:
        report.update(error=str(error), code=error.code)
        print(f'FAIL {error}')
        code = 2
    except (KeyError, TypeError, AttributeError, ValueError, OSError, tarfile.TarError) as error:
        # 元数据缺字段、归档结构异常等未预期情况一律按失败处理，不允许放行。
        report.update(error=f'{type(error).__name__}: {error}',
                      code='REUSE-BACKEND-INVALID')
        print(f'FAIL [REUSE-BACKEND-INVALID] {type(error).__name__}: {error}')
        code = 2
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if dest is not None and dest.is_dir() and dest.parent == delivery_root:
        (dest / 'backend-reuse.json').write_text(text, encoding='utf-8')
    elif args.output:
        output = Path(args.output).resolve()
        if delivery_root in output.parents:
            print('FAIL 只读校验报告不得写入交付根目录')
            return 2
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(text, encoding='utf-8')
    return code


if __name__ == '__main__':
    sys.exit(main())

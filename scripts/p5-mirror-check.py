"""文件说明：P5 Docker Hub镜像站只读核验；确认镜像站能按deploy/p5-images.json的原始完整摘要提供镜像。

对每个镜像站、每个锁定镜像依次检查（与BuildKit拉取路径一致，按摘要寻址，带?ns=docker.io）：
  1. 索引清单HEAD与GET均成功，且返回内容的sha256等于锁定摘要；
  2. 存在linux/arm64子清单，GET后sha256等于子清单摘要；如给出历史证据文件，子清单摘要须与之一致；
  3. 镜像配置blob（几KB）GET后sha256一致，且架构为arm64；
  4. 每个层blob只发HEAD请求（不下载层内容），要求可访问且长度与清单一致。
只读查询，不修改Docker、BuildKit或锁文件；始终使用https并校验证书，不接受任何替代摘要或标签。
用法：python scripts/p5-mirror-check.py --mirror 镜像站A --mirror 镜像站B [--evidence 历史manifest-evidence.json] [--images node,nginx]
"""
import argparse
import hashlib
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INDEX_TYPES = ('application/vnd.oci.image.index.v1+json',
               'application/vnd.docker.distribution.manifest.list.v2+json')
MANIFEST_TYPES = ('application/vnd.oci.image.manifest.v1+json',
                  'application/vnd.docker.distribution.manifest.v2+json')
ACCEPT = ', '.join(INDEX_TYPES + MANIFEST_TYPES)
HOST_PATTERN = re.compile(r'^[A-Za-z0-9.-]+(:[0-9]+)?$')


class CheckError(Exception):
    """单项检查失败；携带阶段名便于定位是清单、配置还是层blob出错。"""

    def __init__(self, stage, message):
        super().__init__(f'{stage}: {message}')
        self.stage = stage


def repository(reference):
    """把锁文件引用转换为Docker Hub仓库路径与摘要；官方镜像补library/。"""
    name, digest = reference.split('@', 1)
    if not re.fullmatch(r'sha256:[a-f0-9]{64}', digest):
        raise ValueError(f'锁文件摘要格式不合法：{reference}')
    name = re.sub(r':[^/]+$', '', name)
    return (name if '/' in name else 'library/' + name), digest


class Registry:
    """最小化的Registry v2客户端：匿名Bearer令牌、按摘要取清单与blob。"""

    def __init__(self, host, timeout):
        self.host, self.timeout, self.tokens = host, timeout, {}

    def _url(self, repo, kind, digest):
        return f'https://{self.host}/v2/{repo}/{kind}/{digest}?ns=docker.io'

    def _token(self, challenge, repo):
        params = dict(re.findall(r'(\w+)="([^"]*)"', challenge))
        if 'realm' not in params or not params['realm'].startswith('https://'):
            raise CheckError('auth', f'无法识别的认证要求：{challenge}')
        query = {'scope': f'repository:{repo}:pull'}
        if params.get('service'):
            query['service'] = params['service']
        url = params['realm'] + '?' + urllib.parse.urlencode(query)
        with urllib.request.urlopen(url, timeout=self.timeout) as response:
            data = json.loads(response.read().decode('utf-8'))
        return data.get('token') or data.get('access_token')

    def request(self, method, repo, kind, digest, accept=ACCEPT):
        url = self._url(repo, kind, digest)
        for attempt in range(2):
            headers = {'Accept': accept,
                       'User-Agent': 'policy-p5-mirror-check'}
            if repo in self.tokens:
                headers['Authorization'] = 'Bearer ' + self.tokens[repo]
            request = urllib.request.Request(
                url, method=method, headers=headers)
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    body = response.read() if method == 'GET' else b''
                    return response.status, dict(response.headers), body
            except urllib.error.HTTPError as error:
                challenge = error.headers.get('WWW-Authenticate', '')
                if error.code == 401 and attempt == 0 and challenge.lower().startswith('bearer'):
                    self.tokens[repo] = self._token(challenge, repo)
                    continue
                raise CheckError(
                    f'{method} {kind}', f'HTTP {error.code} {error.reason}') from None
            except (urllib.error.URLError, TimeoutError, OSError) as error:
                reason = getattr(error, 'reason', error)
                raise CheckError(f'{method} {kind}',
                                 f'连接失败：{reason}') from None
        raise CheckError(f'{method} {kind}', '认证后仍被拒绝')


def sha256(data):
    return 'sha256:' + hashlib.sha256(data).hexdigest()


def check_image(registry, name, reference, expected_arm):
    """按顺序执行四项检查；任一失败即停止该镜像并返回失败阶段。"""
    repo, digest = repository(reference)
    result = {'image': name, 'repository': repo, 'index_digest': digest}
    started = time.monotonic()
    try:
        registry.request('HEAD', repo, 'manifests', digest)
        _, _, body = registry.request('GET', repo, 'manifests', digest)
        if sha256(body) != digest:
            raise CheckError('index', f'返回内容摘要{sha256(body)}与锁定摘要不一致')
        index = json.loads(body.decode('utf-8'))
        arm = [item for item in index.get('manifests', [])
               if item.get('platform', {}).get('os') == 'linux'
               and item.get('platform', {}).get('architecture') == 'arm64']
        if len(arm) != 1:
            raise CheckError('index', f'linux/arm64子清单数量为{len(arm)}')
        child = arm[0]['digest']
        result['arm64_digest'] = child
        if expected_arm and child not in expected_arm:
            raise CheckError(
                'index', f'ARM64子清单{child}与历史证据{sorted(expected_arm)}不一致')
        _, _, body = registry.request(
            'GET', repo, 'manifests', child, accept=', '.join(MANIFEST_TYPES))
        if sha256(body) != child:
            raise CheckError('arm64-manifest', '子清单内容摘要不一致')
        manifest = json.loads(body.decode('utf-8'))
        config = manifest['config']
        _, _, body = registry.request(
            'GET', repo, 'blobs', config['digest'], accept='*/*')
        if sha256(body) != config['digest']:
            raise CheckError('config', '配置blob摘要不一致')
        image_config = json.loads(body.decode('utf-8'))
        if image_config.get('architecture') != 'arm64' or image_config.get('os') != 'linux':
            raise CheckError(
                'config', f"配置架构为{image_config.get('os')}/{image_config.get('architecture')}")
        result['config_digest'] = config['digest']
        result['diff_ids'] = image_config.get('rootfs', {}).get('diff_ids', [])
        layers = manifest.get('layers', [])
        for layer in layers:
            _, headers, _ = registry.request(
                'HEAD', repo, 'blobs', layer['digest'], accept='*/*')
            length = headers.get('Content-Length')
            # 部分镜像站对blob返回重定向后的CDN响应，长度存在时必须一致。
            if length is not None and int(length) != layer['size']:
                raise CheckError(
                    'layer', f"{layer['digest']}长度{length}与清单{layer['size']}不一致")
        result['layers'] = len(layers)
        result['layer_bytes'] = sum(layer['size'] for layer in layers)
        result['status'] = 'PASS'
    except CheckError as error:
        result.update(status='FAIL', stage=error.stage, error=str(error))
    except (ValueError, KeyError, json.JSONDecodeError) as error:
        result.update(status='FAIL', stage='parse', error=f'响应格式异常：{error}')
    result['seconds'] = round(time.monotonic() - started, 2)
    return result


def load_evidence(path):
    """读取历史联网预检的ARM64子清单摘要，用于跨镜像站交叉比对。"""
    if not path:
        return {}
    data = json.loads(Path(path).read_text(encoding='utf-8-sig'))
    return {item['image']: {entry['digest'] for entry in item['arm64']} for item in data}


def main(argv=None):
    parser = argparse.ArgumentParser(description='P5 Docker Hub镜像站只读核验')
    parser.add_argument('--mirror', action='append',
                        required=True, help='镜像站主机名，可重复；只允许https')
    parser.add_argument('--lock', default=str(ROOT / 'deploy/p5-images.json'))
    parser.add_argument('--evidence', default='',
                        help='历史manifest-evidence.json，用于核对ARM64子清单摘要')
    parser.add_argument('--images', default='', help='逗号分隔的镜像名；默认锁文件全部五个')
    parser.add_argument('--timeout', type=float, default=20.0)
    parser.add_argument('--output', default='', help='JSON报告路径；默认只输出到控制台')
    args = parser.parse_args(argv)
    for host in args.mirror:
        if not HOST_PATTERN.fullmatch(host):
            parser.error(f'镜像站必须是主机名（可带端口），不含协议或路径：{host}')
    lock = json.loads(Path(args.lock).read_text(encoding='utf-8'))
    if lock.get('platform') != 'linux/arm64':
        parser.error('锁文件平台必须为linux/arm64')
    wanted = [item for item in args.images.split(
        ',') if item] or list(lock['sources'])
    unknown = set(wanted) - set(lock['sources'])
    if unknown:
        parser.error(f'锁文件中没有这些镜像：{sorted(unknown)}')
    evidence = load_evidence(args.evidence)
    report = {'checked_at_utc': datetime.now(timezone.utc).isoformat(), 'lock': args.lock,
              'evidence': args.evidence or None, 'mirrors': []}
    for host in args.mirror:
        registry = Registry(host, args.timeout)
        images = []
        for name in wanted:
            item = check_image(
                registry, name, lock['sources'][name], evidence.get(name))
            images.append(item)
            detail = item.get(
                'arm64_digest', '') if item['status'] == 'PASS' else item['error']
            print(
                f"[{host}] {name:<8} {item['status']} {item['seconds']}s {detail}", flush=True)
        passed = all(item['status'] == 'PASS' for item in images)
        report['mirrors'].append(
            {'host': host, 'result': 'PASS' if passed else 'FAIL', 'images': images})
        print(f"[{host}] 汇总：{'PASS' if passed else 'FAIL'}", flush=True)
    if args.output:
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output).write_text(json.dumps(
            report, ensure_ascii=False, indent=2), encoding='utf-8')
    return 0 if all(item['result'] == 'PASS' for item in report['mirrors']) else 1


if __name__ == '__main__':
    sys.exit(main())

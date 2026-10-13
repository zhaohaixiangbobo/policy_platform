"""文件说明：P4维护窗口只读快照，对比表内容、业务文件与Qdrant；不输出账号或正文。"""

import argparse
import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[2]


def docker(*args):
    result = subprocess.run(["docker", *args], cwd=ROOT, check=True, capture_output=True,
                            text=True, encoding="utf-8", timeout=60)
    return result.stdout.strip()


def capture():
    result = {"databases": {}}
    for database in ("platform", "knowledge"):
        def sql(query):
            return docker("compose", "exec", "-T", "postgres", "psql", "-U", "postgres",
                          "-d", database, "-tAc", query)
        tables = sql("SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename").splitlines()
        summaries = {}
        for table in tables:
            if not table.replace("_", "").isalnum():
                raise ValueError("非预期表名")
            rows = sql(f'SELECT row_to_json(t)::text FROM "{table}" t ORDER BY row_to_json(t)::text')
            summaries[table] = {"rows": len(rows.splitlines()), "sha256": hashlib.sha256(rows.encode()).hexdigest()}
        result["databases"][database] = summaries
    code = """
import json,hashlib,pathlib,urllib.request
files={}
for root in ('/data/knowledge','/data/materials'):
 for p in sorted(pathlib.Path(root).rglob('*')):
  if p.is_file(): files[str(p)]=hashlib.sha256(p.read_bytes()).hexdigest()
def get(path): return json.load(urllib.request.urlopen('http://qdrant:6333/'+path,timeout=5))['result']
collections={}
for c in get('collections')['collections']:
 name=c['name']; info=get('collections/'+name)
 collections[name]={'points':info['points_count'],'status':info['status']}
print(json.dumps({'files':files,'aliases':get('aliases')['aliases'],'collections':collections},sort_keys=True))
"""
    result.update(json.loads(docker("compose", "--profile", "tools", "run", "--rm", "--no-deps", "-T",
                                    "initialize", "python", "-c", code)))
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--compare", type=Path)
    args = parser.parse_args()
    data = capture()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"tables": {k:len(v) for k,v in data['databases'].items()},
                      "files":len(data['files']),"collections":data['collections'],"aliases":data['aliases']}))
    if args.compare:
        before = json.loads(args.compare.read_text(encoding="utf-8"))
        if before != data:
            raise SystemExit("FAIL: 快照不一致，请核对报告")
        print("PASS: 所有表、业务文件、Alias及collection点数/状态一致")

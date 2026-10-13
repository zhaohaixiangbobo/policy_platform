"""文件说明：真实PG API最小读取冒烟；密码交互输入，仅创建/退出临时会话，不修改业务资料。"""

import argparse
import getpass
import json

import httpx


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--username", required=True)
    args = parser.parse_args()
    base = "http://127.0.0.1:8020/api/v1"
    password = getpass.getpass("管理员密码（不回显、不保存）: ")
    results = {}
    with httpx.Client(timeout=10, trust_env=False) as client:
        response = client.get(base + "/documents")
        results["anonymous_documents"] = response.status_code
        assert response.status_code == 401, "未登录制度访问应被拒绝"
        try:
            response = client.post(base + "/auth/login", json={"username": args.username, "password": password})
            password = None
            response.raise_for_status()
            assert not response.json()["user"]["must_change_password"], "须先完成首次改密"
            for path in ("/auth/me", "/documents?query_scope=CURRENT", "/documents?query_scope=HISTORICAL",
                         "/learning-assessments/current", "/materials"):
                response = client.get(base + path)
                response.raise_for_status()
                results[path] = response.status_code
                if path.startswith("/documents?"):
                    results[path + ":total"] = response.json().get("total")
            print(json.dumps(results, ensure_ascii=False, indent=2))
        finally:
            response = client.post(base + "/auth/logout")
            response.raise_for_status()
            print("临时会话已退出；未执行上传、审核、发布、出题或回答生成")


if __name__ == "__main__":
    main()

"""可选：软删除测试库与本地数据。"""
import argparse
import os
import shutil
import sys

import requests

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from open_ragbench import common


def delete_library(ep: common.Endpoints, library_id: str) -> None:
    resp = requests.delete(f"{ep.libraries}/{library_id}", timeout=30)
    resp.raise_for_status()


def main() -> int:
    parser = argparse.ArgumentParser(description="清理 Open RAG Benchmark 测试库")
    parser.add_argument("--docs-api", default="http://localhost:8790")
    parser.add_argument("--purge", action="store_true", help="同时删除 data/open_ragbench/ 本地数据")
    parser.add_argument("--yes", action="store_true", help="跳过确认")
    args = parser.parse_args()

    library_id = ""
    if common.IMPORT_STATE.exists():
        library_id = common.load_json(common.IMPORT_STATE).get("library_id", "")

    if not args.yes:
        answer = input(f"将删除知识库 {library_id}，是否继续？(y/N) ")
        if answer.strip().lower() != "y":
            print("已取消")
            return 0

    if library_id:
        delete_library(common.Endpoints(args.docs_api), library_id)
        print("已删除知识库:", library_id)
    if args.purge and common.DATA_DIR.exists():
        shutil.rmtree(common.DATA_DIR, ignore_errors=True)
        print("已删除本地数据:", common.DATA_DIR)
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""执行技术文档与架构索引的组合校验。"""
from __future__ import annotations

import sys
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parent
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

import check_architecture_docs
import sync_tech_docs


# 依次执行文档自动同步检查与架构索引检查。
def run() -> int:
    sync_exit_code = sync_tech_docs.run(check_only=True)
    if sync_exit_code != 0:
        return sync_exit_code
    return check_architecture_docs.run()


# 程序入口。
def main() -> int:
    try:
        return run()
    except Exception as error:
        print(str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

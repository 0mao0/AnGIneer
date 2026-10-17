# -*- coding: utf-8 -*-
"""SOP 定义校验 + LLM-free 直跑检查（expression 补全施工用）。

用法：
    python scripts/sop_check.py <sop_id> [<sop_id> ...]
    python scripts/sop_check.py <sop_id> --run '<json context>'

无 --run 时只做：JSON 可解析 + validate_sop_data 全规则（含规则 6 calculator expression）。
有 --run 时额外用 SopRunner 直跑（llm_client=object()，缺参推荐走仅报缺降级，不打网关），
打印每步 status / result / error / missing_report。
退出码：任一 SOP 校验失败或直跑有 error 级问题 → 1。
"""
import json
import os
import sys

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(_ROOT, "services/angineer-core/src"))
sys.path.insert(0, os.path.join(_ROOT, "services/sop-core/src"))
sys.path.insert(0, os.path.join(_ROOT, "services/engtools/src"))

from angineer_core import ports  # noqa: E402
from angineer_core.sop_domain import load_domain_pack  # noqa: E402
from angineer_core.sop_runner import SopRunner  # noqa: E402
from sop_core.sop_validator import build_sop_model, validate_sop_data  # noqa: E402

SOP_DIR = os.path.join(_ROOT, "data", "platform", "sops", "json")


def _register_engtool_port():
    from engtools.BaseTool import ToolRegistry
    ports.register_agent_search(engtool_registry=lambda: ToolRegistry)


def check_one(sop_id: str, ctx: dict | None) -> bool:
    path = os.path.join(SOP_DIR, f"{sop_id}.json")
    if not os.path.exists(path):
        print(f"[{sop_id}] 文件不存在: {path}")
        return False
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    errors = validate_sop_data(data)
    name = data.get("name_zh") or data.get("name") or sop_id
    if errors:
        print(f"[{sop_id}] {name} 校验失败:")
        for e in errors:
            print(f"  - {e}")
        return False
    print(f"[{sop_id}] {name} 校验通过")
    if ctx is None:
        return True
    _register_engtool_port()
    sop = build_sop_model(data)
    runner = SopRunner(domain_hints=load_domain_pack("harbor"), llm_client=object())
    runner.run_sop(sop, dict(ctx))
    ok = True
    for r in runner.memory.history:
        line = f"  {r.step_id}: {r.status}"
        if r.status != "success":
            ok = False
            line += f" error={r.error}"
        print(line)
    return ok


def main() -> int:
    args = sys.argv[1:]
    ctx = None
    if "--run" in args:
        i = args.index("--run")
        ctx = json.loads(args[i + 1])
        args = args[:i]
    if not args:
        print(__doc__)
        return 2
    ok = all(check_one(sid, ctx) for sid in args)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())

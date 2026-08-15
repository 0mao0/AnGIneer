import json
import datetime
from typing import Any, Dict, List, Optional


def now_iso() -> str:
    """获取当前时间 ISO 字符串。"""
    return datetime.datetime.now().isoformat(timespec="seconds")


def summarize_cases(cases: List[Dict[str, Any]]) -> Dict[str, Any]:
    """统计用例数量与失败数。"""
    total = len(cases)
    failed = len([c for c in cases if c.get("status") == "fail"])
    return {"cases": total, "failures": failed}


def build_report(
    suite: str,
    cases: List[Dict[str, Any]],
    summary: Optional[Dict[str, Any]] = None,
    meta: Optional[Dict[str, Any]] = None,
    version: str = "1.0"
) -> Dict[str, Any]:
    """构建统一回归报告结构。"""
    computed_summary = summary or summarize_cases(cases)
    status = "ok" if computed_summary.get("failures", 0) == 0 else "fail"
    return {
        "version": version,
        "suite": suite,
        "timestamp": now_iso(),
        "status": status,
        "summary": computed_summary,
        "cases": cases,
        "meta": meta or {}
    }


def emit_report(report: Dict[str, Any]) -> None:
    """输出统一回归报告到标准输出。"""
    print("\n__REGRESSION_START__")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print("__REGRESSION_END__")

"""P5.5 prompt 字面量审计：services/**/*.py 中 `你是一个|You are a` 检测。

规则：
- `services/angineer-core/src/angineer_core/prompts/` 目录为 prompt 资产唯一许可区；
- 其它 services 源码出现 prompt 字面量即报警（CI 失败）；
- 白名单仅放行本阶段未纳入统一目录的既有 prompt 资产/工具侧 prompt，
  新代码不得新增白名单条目。
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROMPT_PATTERN = re.compile(r"你是一个|You are a")

PROMPTS_DIR = "services/angineer-core/src/angineer_core/prompts"

# 既有独立 prompt 资产 / 工具侧 prompt（P5 未纳入迁移，后续评估归位；禁止新增条目）
WHITELIST = frozenset(
    {
        "services/docs-core/src/docs_core/step07_graph/entity_extractor.py",
        "services/docs-core/src/docs_core/step07_graph/extractor_prompts.py",
        "services/docs-core/src/docs_core/step07_graph/graph_orchestrator.py",
        "services/docs-core/src/docs_core/step07_graph/relation_infer.py",
        "services/engtools/src/engtools/ConditionalTool.py",
        "services/engtools/src/engtools/TableTool.py",
        "services/sop-core/src/sop_core/sop_parser.py",
    }
)


def audit(roots: list[Path]) -> list[str]:
    """返回违规列表；空列表表示通过。"""
    violations: list[str] = []
    for root in roots:
        for path in sorted(root.rglob("*.py")):
            rel = path.relative_to(ROOT).as_posix()
            if rel.startswith(PROMPTS_DIR):
                continue
            if rel in WHITELIST:
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            for lineno, line in enumerate(text.splitlines(), start=1):
                if PROMPT_PATTERN.search(line):
                    violations.append(f"{rel}:{lineno}: {line.strip()[:100]}")
    return violations


def main() -> int:
    violations = audit([ROOT / "services"])
    if violations:
        print("prompt 字面量违规（prompts/ 目录外）：")
        print("\n".join(violations))
        return 1
    print("OK: services 源码中未发现 prompts/ 目录外的 prompt 字面量。")
    return 0


if __name__ == "__main__":
    sys.exit(main())

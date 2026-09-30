"""评测 run manifest（阶段 6）：每次 eval run 的配置/prompt 版本快照，落到 eval_run.config_snapshot。

只记录非敏感配置（模型名/flag/内部 URL），绝不包含 api_key。
"""
import os
from datetime import datetime
from typing import Any, Dict

from angineer_core.prompts import versions as _prompt_versions


def _effective_prompt_versions() -> Dict[str, str]:
    """注册表版本表 + QA 档改写为进程实际生效版本（env 可钉非 latest）。"""
    pv = dict(_prompt_versions())
    try:
        from angineer_core.agent_configs import effective_qa_prompt_version

        pv["agent_configs.qa_system_prompt"] = effective_qa_prompt_version()
    except Exception:  # noqa: BLE001 版本标注失败不阻断 run
        pass
    return pv


def build_run_manifest(config_name: str = "") -> Dict[str, Any]:
    """构建 run 级 manifest：prompt 版本 + 关键开关 + 模型，供纵向对比复现。"""
    from angineer_core.base_config import get_config

    cfg = get_config()
    model = config_name or os.getenv("ANGINEER_DEFAULT_MODEL", "")
    return {
        "schema_version": "eval.run_manifest.v1",
        "prompt_versions": _effective_prompt_versions(),
        "model": model,
        "flags": {
            "route_pre": os.getenv("ANGINEER_ROUTE_PRE", "true"),
            "docs_api_url": os.getenv("ANGINEER_DOCS_API_URL", ""),
            "vectorstore_provider": os.getenv("DOCS_VECTORSTORE_PROVIDER", "chroma"),
        },
        "reranker_url": str(cfg.runner.reranker_url or ""),
        "created_at": datetime.now().isoformat(),
    }

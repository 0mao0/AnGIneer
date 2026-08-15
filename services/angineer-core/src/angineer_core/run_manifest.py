"""评测 run manifest（阶段 6）：每次 eval run 的配置/prompt 版本快照，落到 eval_run.config_snapshot。

只记录非敏感配置（模型名/flag/内部 URL），绝不包含 api_key。
"""
import os
from datetime import datetime
from typing import Any, Dict

from angineer_core.prompts import versions as _prompt_versions


def build_run_manifest() -> Dict[str, Any]:
    """构建 run 级 manifest：prompt 版本 + 关键开关 + 模型，供纵向对比复现。"""
    from angineer_core.base_config import get_config

    cfg = get_config()
    return {
        "schema_version": "eval.run_manifest.v1",
        "prompt_versions": dict(_prompt_versions()),
        "model": os.getenv("ANGINEER_DEFAULT_MODEL", ""),
        "flags": {
            "route_pre": os.getenv("ANGINEER_ROUTE_PRE", "true"),
            "docs_api_url": os.getenv("ANGINEER_DOCS_API_URL", ""),
            "vectorstore_provider": os.getenv("DOCS_VECTORSTORE_PROVIDER", "chroma"),
        },
        "reranker_url": str(cfg.runner.reranker_url or ""),
        "created_at": datetime.now().isoformat(),
    }

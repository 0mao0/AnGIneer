"""v1 resume 阶段计算：实现统一在 docs_core.parse_pipeline（单一真相源），本模块仅再导出。

历史实踩（2026-09-15，宿主侧）：本模块曾自带 _PIPELINE_ORDER 且与 docs-core 漂移——
resume 永远补不上图描述阶段。算法只允许定义在 docs_core.parse_pipeline 一处；
包内保留本模块路径是为兼容 `from docs_core.docs_api.resume_stages import compute_resume_stages`。
"""
from docs_core.parse_pipeline import _PIPELINE_ORDER, compute_resume_stages

DEFAULT_STAGES = ["structure"]

__all__ = ["compute_resume_stages", "_PIPELINE_ORDER", "DEFAULT_STAGES"]

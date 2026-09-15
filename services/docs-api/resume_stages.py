"""v1 resume 阶段计算：实现统一在 docs_core.parse_pipeline（单一真相源），本模块仅再导出。

历史实踩（2026-09-15）：本模块曾自带 _PIPELINE_ORDER 与算法，且顺序缺 figure_describe、
与 docs-core 漂移——resume 永远补不上图描述阶段。算法只允许定义在 docs-core 一处；
保留本模块路径是为兼容 `from resume_stages import compute_resume_stages`（v1 路由引用）。
"""
from docs_core.parse_pipeline import _PIPELINE_ORDER, compute_resume_stages

DEFAULT_STAGES = ["structure"]

__all__ = ["compute_resume_stages", "_PIPELINE_ORDER", "DEFAULT_STAGES"]

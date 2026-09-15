"""resume_stages 单一真相源守卫：docs-api 侧必须只是 docs_core.parse_pipeline 的再导出。

历史实踩（2026-09-15）：本模块曾自带 _PIPELINE_ORDER 且缺 figure_describe，与 docs-core 漂移——
resume 永远补不上图描述阶段。顺序/算法只允许定义在 docs-core 一处。
"""
from docs_core.parse_pipeline import _PIPELINE_ORDER as CORE_ORDER
from docs_core.parse_pipeline import compute_resume_stages as core_compute

import resume_stages


def test_reexport_is_the_same_object():
    assert resume_stages.compute_resume_stages is core_compute


def test_pipeline_order_matches_core():
    assert resume_stages._PIPELINE_ORDER == CORE_ORDER
    assert "figure_describe" in resume_stages._PIPELINE_ORDER, "漂移守卫：复制版当年就漏了这个阶段"


def test_v1_route_import_shape():
    # routes/v1/documents.py 用 `from resume_stages import compute_resume_stages`，形状必须保持
    from resume_stages import compute_resume_stages  # noqa: F401

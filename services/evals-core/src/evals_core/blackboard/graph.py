"""M0 离线图的**薄壳**：实现已上收引擎（``angineer_core.conv_graph``），本模块只做别名导出。

为什么上收：cites join / 召回 / 渲染是**生产读写路径与 M0 离线壳共用的同一段逻辑**，
两份实现必然漂移（BB §3.2 的 join 口径是单一真相源）。M0 的 API 保持不变，历史调用方无感。

保留的 M0 语义（由引擎实现保证，见 ``angineer_core.conv_graph`` 的模块 docstring）：
- 只把**被引用**的 item 建成 clause 节点（``[KTE]x`` × ``items[].metadata.cite``，限单 run）；
- value 节点必须带单位且能在本轮 assistant 原文回查（BB §3.3）；
- 召回 = 序数消解（指向最近一个产出过引用的轮）→ 编号/token 匹配 → 近邻兜底；
- 渲染固定版式、自描述、不带 ``[Kx]``，默认上限 = ``subgraph_est_cap() * 2`` 字符。
"""
from angineer_core.conv_graph import (  # noqa: F401
    REFERENCE_RE,
    VALUE_RE,
    MARKER_RE,
    Edge,
    Graph as OfflineGraph,
    Node,
    build_graph,
    last_section_segment,
    ordinal_value as _ordinal_value,
    recall,
    render,
    strip_doc_extension as _strip_ext,
)

__all__ = ["Edge", "Node", "OfflineGraph", "build_graph", "recall", "render",
           "MARKER_RE", "VALUE_RE", "REFERENCE_RE"]

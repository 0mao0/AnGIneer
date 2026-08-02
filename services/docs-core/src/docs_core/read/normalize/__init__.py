"""docs_core normalize 阶段导出（阶段五收敛）：对外只暴露五个入口模块。

- ``popo``：PoPo 后端（子进程管线 + mapper + 表格内容通道）
- ``solo``：solo 降级后端（rows→graph + G3 适配器）
- ``title_level_refiner``：标题层级 LLM 校正器（输入 CanonicalBlock）
- ``table_semantics`` / ``formula_semantics``：语义层通用增强器（输入 Canonical 对象）

内部生产代码请从上述子模块直接导入，不要使用扁平命名空间。
"""
from . import popo
from .structure import solo
from .structure import title_level_refiner
from .semantics import formula_semantics
from .semantics import table_semantics

__all__ = [
    "popo",
    "solo",
    "title_level_refiner",
    "table_semantics",
    "formula_semantics",
]

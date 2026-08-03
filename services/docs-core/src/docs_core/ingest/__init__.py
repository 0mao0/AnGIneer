"""docs_core ingest 层：结构 + 语义 -> CanonicalDocument（内存对象），是 write/query 的上游契约。"""

from . import canonical, semantics, structure

__all__ = [
    "canonical",
    "semantics",
    "structure",
]

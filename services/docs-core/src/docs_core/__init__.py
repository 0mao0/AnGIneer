"""docs_core — 统一知识管理包：文档处理、知识图谱、检索、文本转SQL、定时维护"""

from .docs_service import DocsService, get_docs_service, docs_service

# 全流水线共享契约（04/05/06/09 + docs_service 根）
from .models.types import (
    CanonicalBlock,
    CanonicalDocument,
    CanonicalTable,
    CanonicalChunk,
    CanonicalOutlineNode,
    CitationTarget,
    BoundingBox,
)
# 步骤七：知识图谱
from .step07_graph import (
    EntityLayer,
    RelationType,
    EntitySeed,
    Confidence,
    GraphEntity,
    GraphRelation,
    GraphStore,
    GraphOrchestrator,
    EvidencePacket,
    build_evidence_packets,
    QuestionMapper,
    StructuredQuestion,
    RelationInferrer,
    EntityExtractor,
)
# 步骤八：维护
from .step08_maintain import (
    DreamCycleRunner,
    DreamCycleReport,
    DreamCycleConfig,
    get_config as get_dream_cycle_config,
)

__all__ = [
    "DocsService",
    "get_docs_service",
    "docs_service",
    "CanonicalBlock",
    "CanonicalDocument",
    "CanonicalTable",
    "CanonicalChunk",
    "CanonicalOutlineNode",
    "CitationTarget",
    "BoundingBox",
    "EntityLayer",
    "RelationType",
    "EntitySeed",
    "Confidence",
    "GraphEntity",
    "GraphRelation",
    "GraphStore",
    "GraphOrchestrator",
    "EvidencePacket",
    "build_evidence_packets",
    "QuestionMapper",
    "StructuredQuestion",
    "RelationInferrer",
    "EntityExtractor",
    "DreamCycleRunner",
    "DreamCycleReport",
    "DreamCycleConfig",
    "get_dream_cycle_config",
]

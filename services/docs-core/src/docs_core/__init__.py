"""docs_core — 统一知识管理包：文档处理、知识图谱、检索、文本转SQL、定时维护"""

from .knowledge_service import KnowledgeService, get_knowledge_service, knowledge_service

# write pipeline
from .write.ingest.organize.types import (
    CanonicalBlock,
    CanonicalDocument,
    CanonicalTable,
    CanonicalChunk,
    CanonicalOutlineNode,
    CitationTarget,
    BoundingBox,
)
from .write.graph import (
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

# maintain pipeline
from .maintain.cycle import (
    DreamCycleRunner,
    DreamCycleReport,
    DreamCycleConfig,
    get_config as get_dream_cycle_config,
)

__all__ = [
    "KnowledgeService",
    "get_knowledge_service",
    "knowledge_service",
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

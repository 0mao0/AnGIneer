"""Orchestrator for the knowledge graph construction pipeline (Operation 1)."""

import logging
from typing import Any, Dict, List, Optional

from knowledge_graph.config import Confidence, EntityLayer, EntitySeed, RelationType, load_seed_entities
from knowledge_graph.graph_store import GraphEntity, GraphRelation, GraphStore
from knowledge_graph.entity_extractor import EntityExtractor
from knowledge_graph.relation_infer import RelationInferrer
from knowledge_graph.evidence_builder import EvidencePacket

logger = logging.getLogger(__name__)


class GraphOrchestrator:
    """Orchestrates the graph construction lifecycle:
    1. Load seed entities
    2. Expand from evidence packets (entity + relation extraction)
    3. Human review interface
    """

    def __init__(self, store: GraphStore):
        self.store = store
        self.extractor = EntityExtractor()
        self.inferrer = RelationInferrer()

    def load_seed_entities(self, seeds: Optional[List[EntitySeed]] = None) -> int:
        """Load seed entities into the graph store. Returns count of entities added."""
        if seeds is None:
            seeds = load_seed_entities()
        count = 0
        for seed in seeds:
            entity = GraphEntity(
                name=seed.name,
                layer=seed.layer,
                aliases=seed.aliases,
                description=seed.description,
            )
            self.store.upsert_entity(entity)
            count += 1
        logger.info("Loaded %d seed entities", count)
        return count

    def expand_from_packet(
        self,
        packet: EvidencePacket,
        seed_entity_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Operation 1 Step 3: AI scans a packet for seed entities,
        extracts new entities and relationships."""
        text = packet.raw_text

        if seed_entity_name:
            seed_entities = [s for s in load_seed_entities() if s.name == seed_entity_name]
        else:
            seed_entities = load_seed_entities()

        occurrences = self.extractor.find_seed_occurrences(text, seed_entities)
        if not occurrences:
            return {"packet_id": packet.packet_id, "entities_found": 0, "relations_added": 0}

        entity_count = 0
        relation_count = 0

        for seed_name, _ in occurrences:
            seed = next((s for s in seed_entities if s.name == seed_name), None)
            if seed is None:
                continue

            related = self.extractor.find_related_entities(text, seed.name, seed_entities)

            for entity_name in related:
                layer = self.extractor.classify_entity(entity_name)
                self.store.upsert_entity(GraphEntity(
                    name=entity_name,
                    layer=layer,
                    source_doc=packet.doc_title,
                    source_clause=packet.section_path,
                ))
                entity_count += 1

            if related:
                seed_entity = self.store.get_entity_by_name(seed.name)
                if seed_entity:
                    for related_name in related:
                        related_entity = self.store.get_entity_by_name(related_name)
                        if related_entity:
                            rtype = RelationType.CONSTRAINS
                            if seed.layer == EntityLayer.CONDITION:
                                rtype = RelationType.CONDITIONS_ON
                            elif seed.layer == EntityLayer.ACTION:
                                rtype = RelationType.COMPUTES_FROM
                            self.store.add_relation(
                                source_id=seed_entity.entity_id,
                                target_id=related_entity.entity_id,
                                relation_type=rtype,
                                confidence=Confidence.AI_EXTRACTED,
                                source_clause=packet.section_path,
                            )
                            relation_count += 1

        return {
            "packet_id": packet.packet_id,
            "entities_found": entity_count,
            "relations_added": relation_count,
        }

    def expand_all_packets(
        self,
        packets: List[EvidencePacket],
    ) -> Dict[str, Any]:
        """Run entity expansion across all evidence packets."""
        total_entities = 0
        total_relations = 0
        for packet in packets:
            result = self.expand_from_packet(packet)
            total_entities += result.get("entities_found", 0)
            total_relations += result.get("relations_added", 0)
        return {
            "packets_processed": len(packets),
            "total_entities_found": total_entities,
            "total_relations_added": total_relations,
        }

    def get_graph_snapshot(self) -> Dict[str, Any]:
        """Return a full graph snapshot for human review."""
        entities = self.store.list_all_entities()
        entity_map = {
            e.entity_id: {"id": e.entity_id, "name": e.name, "layer": e.layer.value,
                          "aliases": e.aliases, "source_clause": e.source_clause}
            for e in entities
        }

        relations = []
        for e in entities:
            for rel in self.store.get_relations_by_entity(e.entity_id, direction="outgoing"):
                source = entity_map.get(rel.source_id, {}).get("name", rel.source_id)
                target = entity_map.get(rel.target_id, {}).get("name", rel.target_id)
                relations.append({
                    "relation_id": rel.relation_id,
                    "source": source,
                    "target": target,
                    "type": rel.relation_type,
                    "confidence": rel.confidence,
                    "evidence": rel.evidence_text,
                    "clause": rel.source_clause,
                    "conflict_note": rel.conflict_note,
                })

        return {
            "stats": self.store.get_stats(),
            "entities": list(entity_map.values()),
            "relations": relations,
        }

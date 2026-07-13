"""Orchestrator for the knowledge graph construction pipeline (Operation 1)."""

import json
import logging
import time
from typing import Any, Dict, List, Optional

from knowledge_graph.config import Confidence, EntityLayer, EntitySeed, RelationType, load_seed_entities
from knowledge_graph.graph_store import GraphEntity, GraphRelation, GraphStore
from knowledge_graph.entity_extractor import EntityExtractor, MAX_TEXT_CHARS
from knowledge_graph.extractor_prompts import (
    SYSTEM_PROMPT_E1_FRAMEWORK,
    SYSTEM_PROMPT_E2_PRINCIPLE,
    SYSTEM_PROMPT_E3_CASE,
    SYSTEM_PROMPT_E4_COUNTEREXAMPLE,
    SYSTEM_PROMPT_E5_GLOSSARY,
    USER_PROMPT_TEMPLATE_NO_SECTION,
)
from knowledge_graph.relation_infer import RelationInferrer
from knowledge_graph.evidence_builder import EvidencePacket
from ai_inference.llm_client import LLMClient

logger = logging.getLogger(__name__)

VERIFY_SYSTEM_PROMPT = """You are a rigorous engineering standard relationship validator.
Your task is to test whether entity relationships extracted from a technical document meet three quality criteria.

For each extracted relationship, you must evaluate it against all three criteria below.
You MUST produce a detailed justification for each gate — not just a yes/no — so that reviewers can audit your reasoning.
Relationships that pass ALL THREE gates earn high confidence.
Relationships that fail some gates are still recorded but with lower confidence and a rejection explanation.

## Gate V1 — Cross-Domain Validation

**Question**: Does this relationship have evidence from at least TWO independent contexts within the text?

Definition of "independent context":
- Different sections or chapters (not the same section paraphrased)
- Different entity groups or parameters (not the same pair described twice)
- Different logical conclusions (not the same reasoning chain presented in two places)

Judgment standard:
- PASS: the relationship is mentioned in at least two genuinely different places, with different surrounding entities or different conditions. For example: "bearing capacity verification depends on design water level" — stated in both Section 3 (load combinations) and Section 5 (stability checks), with different parameter sets each time.
- FAIL: the relationship only appears once, or the "two occurrences" are just the same sentence re-quoted, or the same example rephrased slightly — this counts as ONE occurrence, not two.

## Gate V2 — Predictive Power

**Question**: If we give this relationship to an engineer unfamiliar with this document, can they use it to answer a question that the document does NOT explicitly discuss?

You must:
1. Invent a novel, realistic engineering scenario that is NOT directly discussed in the provided text.
2. Attempt to answer it using only this relationship.
3. Judge whether the resulting answer is meaningful and non-trivial.

Judgment standard:
- PASS: the relationship enables a non-obvious deduction. For example, "wave force calculation depends on design wave height" → novel question: "If we change the breakwater length from 200m to 350m, does the wave force formula need recalibration?" → answer: wave force depends on wave height, not breakwater length directly; recalibration is only needed if wave height changes at the new location → a non-obvious, useful engineering judgment.
- FAIL: the relationship can only produce tautologies or generic advice. For example, "concrete requires cement" → the only possible answer is "we need cement to make concrete" — a tautology with zero predictive value.

Anti-cheat rule: The novel scenario you invent must NOT be something the text itself already discusses. If someone skimming the document could answer the question without this relationship, the question is not novel and the test is invalid.

## Gate V3 — Uniqueness (Exclusivity)

**Question**: Is this relationship a non-trivial, domain-specific engineering insight, or is it something any competent engineer would already know?

Evaluation criteria:
- Unique standard perspective: Does it express a specific standard's particular requirement (e.g., "design high water level constrains stability verification" — the standard specifically mandates the HIGH water level, not the average or low water level)?
- Counter-intuitive: Would an engineer unfamiliar with this specific standard make a different assumption?
- Non-obvious conditional coupling: Does it involve specific coefficients, safety margins, or conditional rules that are not universally applicable?

Judgment standard:
- PASS: the relationship reflects a specific standard's engineering judgment, not general textbook knowledge. For example: "seismic condition modifies bearing capacity verification" — generic engineers might check bearing capacity and seismic resistance separately, but this standard explicitly couples them with a reduction factor, which is non-obvious.
- PASS: "ship impact force constrains fender design" — the chain (ship type → berthing energy → fender type → wharf structure dimension) is a standard-specific engineering dependency chain, not universally taught.
- FAIL: any engineer would agree with this without reading the standard. For example: "foundation relies on soil properties" — universal civil engineering knowledge, no standard needed.

Anti-cheat rule: A relationship is NOT unique just because it uses technical jargon or sounds formal. Strip away the domain terminology: if the underlying logic is "A uses B" where both are obvious, it fails V3. The litmus test: would a competent engineer who has never read this specific standard still know this relationship? If yes → FAIL.

## Quality Expectations

- Expected overall pass rate (V1+V2+V3 all passed): 25–50% of extracted relationships.
- If >80% pass: your standards are too loose — re-examine V3 especially; many "passes" are likely just domain-common-sense.
- If <5% pass: the extractor may have produced noise, or your rejection threshold is too strict.
- Every rejection MUST include a specific "rejection_reason" for the audit trail, so users can later retrieve and re-evaluate rejected relationships.

## Output Format

Return a JSON object:

```json
{
  "verified": [
    {
      "from": "entity A",
      "to": "entity B",
      "type": "relation type",
      "passed": 3,
      "V1_cross_domain": {
        "passed": true,
        "evidences": ["Section N: quote...", "Section M: quote..."]
      },
      "V2_predictive_power": {
        "passed": true,
        "novel_scenario": "If X happens, how should we adjust Y?",
        "derived_answer": "Based on this relationship, we would..."
      },
      "V3_uniqueness": {
        "passed": true,
        "why_not_common": "This is non-obvious because..."
      },
      "rejection_reason": ""
    },
    {
      "from": "entity C",
      "to": "entity D",
      "type": "constrains",
      "passed": 1,
      "V1_cross_domain": { "passed": false, "evidences": [] },
      "V2_predictive_power": { "passed": false, "novel_scenario": "", "derived_answer": "" },
      "V3_uniqueness": { "passed": true, "why_not_common": "..." },
      "rejection_reason": "Failed V1 (no cross-domain evidence) and V2 (no predictive power). Only supported by a single occurrence; too generic to enable novel engineering judgments."
    }
  ]
}
```

IMPORTANT: For every relationship, output ALL fields — even if some gates fail. The "passed" field is the count (0-3) of gates that passed. The "rejection_reason" field summarizes WHY it failed, using specific reasons not generic labels."""

ZETTELKASTEN_SYSTEM_PROMPT = """You are a Zettelkasten semantic linking engine for engineering knowledge graphs.

Your task: analyze a set of engineering entities extracted from a single document, and discover IMPLICIT cross-section connections between them — connections that are NOT directly spelled out in any single section, but emerge when you consider the document as a whole.

## Three Types of Connections

1. **depends-on** (one entity's definition or calculation logically depends on another):
   - Example: "stability verification" depends-on "design high water level" — because the stability formula uses the high water level as a boundary condition, even if this is stated in different chapters.

2. **contrasts-with** (two entities represent alternative design choices or conflicting approaches):
   - Example: "gravity wharf" contrasts-with "pile-supported wharf" — they are mutually exclusive structural solutions for the same problem.

3. **composes-with** (two entities are frequently combined in practice as part of a larger system):
   - Example: "bollard" composes-with "fender system" — they jointly form the mooring subsystem of a wharf.

## Execution Rules

1. Scan ALL provided entities. Consider every meaningful pair, but only output connections where there is a genuine, document-supported semantic link — NOT superficial keyword overlap.
2. Connections must be IMPLICIT: they should not be directly stated in a single sentence together. If two entities co-occur in the same sentence frequently, that is co-occurrence, not a Zettelkasten link. Zettelkasten links bridge entities that appear in DIFFERENT sections but are logically connected.
3. Do NOT force connections. If two entities have no real dependency, contrast, or composition relationship, simply do not include them.
4. **Moderation principle**: for a set of 10 entities, expect roughly 5–10 reasonable connections. Fewer than 3 means you may be too conservative; more than 18 means you are likely inventing connections. Adjust proportionally for your entity count.

## Output Format

Return a JSON object:

```json
{
  "connections": [
    {
      "from": "entity A",
      "to": "entity B",
      "connection_type": "depends-on|contrasts-with|composes-with",
      "relation_type": "requires|constrains|conditions_on|verifies|defines",
      "evidence": "Brief explanation of the implicit link, referencing which sections/chapters each entity comes from and why they are connected despite being in different sections.",
      "confidence": 0.3
    }
  ]
}
```

Note: "connection_type" describes the Zettelkasten semantic relationship category.
"relation_type" maps it to the engineering knowledge graph relation type:
- depends-on → "requires"
- contrasts-with → "constrains"  
- composes-with → "defines"
Choose the best mapping; if a connection spans multiple types, pick the dominant one.

Only return connections that are logically sound and document-supported. Quality over quantity."""

VERIFY_MAX_TEXT = 6000


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
        enable_llm: bool = False,
    ) -> Dict[str, Any]:
        """Operation 1 Step 3: AI scans a packet for seed entities,
        extracts new entities and relationships."""
        text = packet.raw_text
        doc_title = packet.doc_title or packet.doc_id

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
                    source_doc=doc_title,
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
                                library_id=packet.library_id,
                                doc_id=packet.doc_id,
                            )
                            relation_count += 1

        if enable_llm:
            llm_result = self._llm_extract(packet, [s[0] for s in occurrences])
            entity_count += llm_result.get("entities_found", 0)
            relation_count += llm_result.get("relations_added", 0)

        return {
            "packet_id": packet.packet_id,
            "entities_found": entity_count,
            "relations_added": relation_count,
        }

    def expand_all_packets(
        self,
        packets: List[EvidencePacket],
        enable_llm: bool = False,
    ) -> Dict[str, Any]:
        """Run entity expansion across all evidence packets."""
        total_entities = 0
        total_relations = 0
        for packet in packets:
            result = self.expand_from_packet(packet, enable_llm=enable_llm)
            total_entities += result.get("entities_found", 0)
            total_relations += result.get("relations_added", 0)

        if enable_llm and packets:
            doc_id = packets[0].doc_id
            library_id = packets[0].library_id
            all_entities = self.store.list_all_entities()
            entity_names = [e.name for e in all_entities]
            doc_summary = packets[0].doc_title or doc_id
            zk_result = self._link_zettelkasten(doc_id, library_id, entity_names, doc_summary)
            total_relations += zk_result.get("relations_added", 0)
            document_text = " ".join(p.raw_text for p in packets if p.raw_text)
            extractor_result = self._run_extractors(doc_id, library_id, entity_names, document_text)
            total_entities += extractor_result.get("entities_updated", 0)

        return {
            "packets_processed": len(packets),
            "total_entities_found": total_entities,
            "total_relations_added": total_relations,
        }

    def get_graph_snapshot(self, library_id: Optional[str] = None, doc_id: Optional[str] = None) -> Dict[str, Any]:
        """Return a graph snapshot, optionally filtered by (library_id, doc_id)."""
        if library_id and doc_id:
            entities = self.store.list_entities_by_doc(library_id, doc_id)
            relations = self.store.get_relations_by_doc(library_id, doc_id)
            stats = self.store.get_stats(library_id=library_id, doc_id=doc_id)
        else:
            entities = self.store.list_all_entities()
            relations = []
            for e in entities:
                for rel in self.store.get_relations_by_entity(e.entity_id, direction="outgoing"):
                    relations.append(rel)
            stats = self.store.get_stats()

        entity_map = {
            e.entity_id: {"id": e.entity_id, "name": e.name, "layer": e.layer.value,
                          "aliases": e.aliases, "source_clause": e.source_clause}
            for e in entities
        }

        rel_list = []
        for rel in relations:
            if rel.relation_type == "constrains":
                continue
            source = entity_map.get(rel.source_id, {}).get("name", rel.source_id)
            target = entity_map.get(rel.target_id, {}).get("name", rel.target_id)
            rel_list.append({
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
            "stats": stats,
            "entities": list(entity_map.values()),
            "relations": rel_list,
        }

    def _llm_extract(self, packet: EvidencePacket, seed_names: List[str]) -> Dict[str, Any]:
        entity_count = 0
        relation_count = 0
        text = packet.raw_text
        doc_title = packet.doc_title or packet.doc_id
        llm_result = self.extractor.extract_from_packet(text, packet.section_path, seed_names)
        llm_entities = llm_result.get("entities", [])
        llm_relations = llm_result.get("relationships", [])

        for ent in llm_entities:
            name = ent.get("name", "").strip()
            if not name:
                continue
            layer_str = ent.get("layer", "")
            try:
                layer = EntityLayer(layer_str)
            except ValueError:
                layer = self.extractor.classify_entity(name)
            self.store.upsert_entity(GraphEntity(
                name=name,
                layer=layer,
                source_doc=doc_title,
                source_clause=packet.section_path,
            ))
            entity_count += 1

        for rel in llm_relations:
            src_name = rel.get("from", "").strip()
            tgt_name = rel.get("to", "").strip()
            if not src_name or not tgt_name:
                continue
            rtype_str = rel.get("type", "")
            try:
                rtype = RelationType(rtype_str)
            except ValueError:
                continue
            raw_confidence = rel.get("confidence", 0.3)
            if not isinstance(raw_confidence, (int, float)):
                raw_confidence = 0.3
            confidence = max(0.0, min(1.0, float(raw_confidence)))
            evidence = rel.get("evidence", "")

            src_entity = self.store.get_entity_by_name(src_name)
            tgt_entity = self.store.get_entity_by_name(tgt_name)
            if src_entity and tgt_entity:
                self.store.add_relation(
                    source_id=src_entity.entity_id,
                    target_id=tgt_entity.entity_id,
                    relation_type=rtype,
                    confidence=confidence,
                    evidence_text=evidence,
                    source_clause=packet.section_path,
                    library_id=packet.library_id,
                    doc_id=packet.doc_id,
                )
                relation_count += 1

        if llm_relations:
            verify_result = self._verify_relations(llm_relations, text, [s[0] if isinstance(s, tuple) else s for s in seed_names])
            for vr in verify_result.get("verified", []):
                src_name = vr.get("from", "").strip()
                tgt_name = vr.get("to", "").strip()
                rtype_str = vr.get("type", "")
                if not src_name or not tgt_name:
                    continue
                try:
                    verified_type = RelationType(rtype_str)
                except ValueError:
                    continue
                passed = vr.get("passed", 0)
                rejection = vr.get("rejection_reason", "")
                src_entity = self.store.get_entity_by_name(src_name)
                tgt_entity = self.store.get_entity_by_name(tgt_name)

                evidence_parts = []
                v1 = vr.get("V1_cross_domain", {})
                if v1.get("passed") and v1.get("evidences"):
                    evidence_parts.append("V1: " + "; ".join(v1["evidences"]))
                v2 = vr.get("V2_predictive_power", {})
                if v2.get("passed") and v2.get("novel_scenario"):
                    evidence_parts.append("V2: " + v2["novel_scenario"])
                v3 = vr.get("V3_uniqueness", {})
                if v3.get("passed") and v3.get("why_not_common"):
                    evidence_parts.append("V3: " + v3["why_not_common"])
                verification_note = "\n".join(evidence_parts) if evidence_parts else ""
                if rejection:
                    verification_note = (verification_note + "\n\nREJECTION: " + rejection).strip()

                if src_entity and tgt_entity:
                    if passed >= 3:
                        self.store.add_relation(
                            source_id=src_entity.entity_id,
                            target_id=tgt_entity.entity_id,
                            relation_type=verified_type,
                            confidence=Confidence.QUESTION_VALIDATED,
                            evidence_text=verification_note,
                            source_clause=packet.section_path,
                            library_id=packet.library_id,
                            doc_id=packet.doc_id,
                        )
                    elif rejection:
                        self.store.add_relation(
                            source_id=src_entity.entity_id,
                            target_id=tgt_entity.entity_id,
                            relation_type=verified_type,
                            confidence=Confidence.AI_EXTRACTED,
                            evidence_text=verification_note,
                            source_clause=packet.section_path,
                            library_id=packet.library_id,
                            doc_id=packet.doc_id,
                        )

        return {"entities_found": entity_count, "relations_added": relation_count}

    def _verify_relations(
        self, relations: List[Dict[str, Any]], packet_text: str, seed_names: List[str]
    ) -> Dict[str, Any]:
        if not relations:
            return {"verified": []}
        seeds_str = ", ".join(seed_names[:10])
        rel_lines = []
        for r in relations:
            rel_lines.append(f'"{r.get("from", "")}" {r.get("type", "")} "{r.get("to", "")}"')

        prompt = (
            "Evaluate each relationship below using the three verification gates (V1/V2/V3) described in the system prompt.\n\n"
            f"Document seeds: {seeds_str}\n\n"
            "Extracted relationships:\n" + "\n".join(rel_lines) +
            "\n\nSource text:\n" + packet_text[:VERIFY_MAX_TEXT]
        )
        try:
            client = LLMClient()
            response = client.chat(
                messages=[
                    {"role": "system", "content": VERIFY_SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                config_name=self.extractor.config_name,
                mode=self.extractor.mode,
            )
        except Exception as e:
            logger.warning("Triple verification LLM call failed: %s", e)
            return {"verified": []}
        return self._parse_json_response(response, "verified")

    def _link_zettelkasten(
        self, doc_id: str, library_id: str, entity_names: List[str], doc_summary: str
    ) -> Dict[str, Any]:
        if len(entity_names) < 3:
            return {"relations_added": 0}
        entity_list = ", ".join(entity_names[:50])
        prompt = (
            f"Document: {doc_summary}\n\n"
            f"All entities (scan every pair, but only output genuine connections):\n{entity_list}\n\n"
            "Discover implicit cross-section connections. Only output connections with clear semantic support. "
            "Do NOT force connections. Do NOT output entities that merely co-occur in the same section."
        )
        try:
            client = LLMClient()
            response = client.chat(
                messages=[
                    {"role": "system", "content": ZETTELKASTEN_SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                config_name=self.extractor.config_name,
                mode=self.extractor.mode,
            )
        except Exception as e:
            logger.warning("Zettelkasten LLM call failed: %s", e)
            return {"relations_added": 0}

        parsed = self._parse_json_response(response, "connections")
        connections = parsed.get("connections", []) if isinstance(parsed, dict) else []

        count = 0
        for conn in connections:
            src_name = conn.get("from", "").strip()
            tgt_name = conn.get("to", "").strip()
            rtype_str = conn.get("relation_type", "")
            zk_type = conn.get("connection_type", "")
            if not src_name or not tgt_name:
                continue
            try:
                rtype = RelationType(rtype_str)
            except ValueError:
                continue
            evidence = conn.get("evidence", "")
            if zk_type:
                evidence = f"[{zk_type}] {evidence}"
            src_entity = self.store.get_entity_by_name(src_name)
            tgt_entity = self.store.get_entity_by_name(tgt_name)
            if src_entity and tgt_entity:
                self.store.add_relation(
                    source_id=src_entity.entity_id,
                    target_id=tgt_entity.entity_id,
                    relation_type=rtype,
                    confidence=Confidence.AI_EXTRACTED,
                    evidence_text=evidence,
                    library_id=library_id,
                    doc_id=doc_id,
                )
                count += 1

        return {"relations_added": count}

    @staticmethod
    def _parse_json_response(response: str, key: str) -> Dict[str, Any]:
        try:
            raw = response.strip()
            fence_start = raw.find("```")
            if fence_start >= 0:
                raw = raw[fence_start + 3:]
                json_marker = raw.find("json")
                if json_marker == 0:
                    raw = raw[4:]
            fence_end = raw.rfind("```")
            if fence_end >= 0:
                raw = raw[:fence_end]
            parsed = json.loads(raw.strip())
            return parsed if isinstance(parsed, dict) and key in parsed else {key: []}
        except Exception:
            logger.warning("Failed to parse JSON response for key=%s", key)
            return {key: []}

    def _run_extractors(
        self, doc_id: str, library_id: str, entity_names: List[str], document_text: str
    ) -> Dict[str, Any]:
        if not document_text or len(entity_names) < 2:
            return {"entities_updated": 0}
        CHUNK_SIZE = 12000
        chunks = [document_text[i:i + CHUNK_SIZE] for i in range(0, len(document_text), CHUNK_SIZE)]
        entity_names_str = ", ".join(entity_names[:50])
        total_updated = 0
        extractor_configs = [
            ("frameworks", SYSTEM_PROMPT_E1_FRAMEWORK),
            ("principles", SYSTEM_PROMPT_E2_PRINCIPLE),
            ("cases", SYSTEM_PROMPT_E3_CASE),
            ("warnings", SYSTEM_PROMPT_E4_COUNTEREXAMPLE),
            ("glossary", SYSTEM_PROMPT_E5_GLOSSARY),
        ]
        for chunk_idx, chunk in enumerate(chunks):
            for key, system_prompt in extractor_configs:
                prompt = USER_PROMPT_TEMPLATE_NO_SECTION.format(entity_names=entity_names_str, text_segment=chunk)
                try:
                    client = LLMClient()
                    response = client.chat(
                        messages=[
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": prompt},
                        ],
                        config_name=self.extractor.config_name,
                        mode=self.extractor.mode,
                    )
                    parsed = self._parse_extractor_response(response, key)
                except Exception as e:
                    logger.warning("Extractor %s chunk %d failed: %s", key, chunk_idx, e)
                    continue
                if key == "frameworks":
                    for fw in parsed:
                        self.store.add_framework(
                            name=fw.get("name", ""),
                            steps_json=json.dumps(fw.get("steps", []), ensure_ascii=False),
                            entry_condition=fw.get("entry_condition", ""),
                            source_section=fw.get("source_section", ""),
                            entity_path=fw.get("entity_path", []),
                            library_id=library_id,
                            doc_id=doc_id,
                        )
                elif key == "principles":
                    for pr in parsed:
                        self.store.add_principle(
                            principle_text=pr.get("principle", ""),
                            category=pr.get("category", "mandatory"),
                            entity_names=pr.get("applies_to_entities", []),
                            source_clause=pr.get("source_clause", ""),
                            evidence_quote=pr.get("evidence_quote", ""),
                            library_id=library_id,
                            doc_id=doc_id,
                        )
                elif key == "cases":
                    for ca in parsed:
                        self.store.add_example(
                            title=ca.get("case_title", ""),
                            inputs_json=json.dumps(ca.get("inputs_json", {}), ensure_ascii=False),
                            computation_text=ca.get("computation_text", ""),
                            entity_names=ca.get("involved_entities", []),
                            source_section=ca.get("source_section", ""),
                            library_id=library_id,
                            doc_id=doc_id,
                        )
                elif key == "warnings":
                    for wa in parsed:
                        self.store.add_warning(
                            warning_text=wa.get("warning_text", ""),
                            category=wa.get("category", ""),
                            severity=wa.get("severity", "quality"),
                            entity_names=wa.get("relates_to_entities", []),
                            source_section=wa.get("source_section", ""),
                            library_id=library_id,
                            doc_id=doc_id,
                        )
                elif key == "glossary":
                    for gl in parsed:
                        self.store.update_entity_glossary(
                            term=gl.get("term", ""),
                            definition=gl.get("definition", ""),
                            aliases=gl.get("aliases", []),
                            source_section=gl.get("source_section", ""),
                        )
                total_updated += len(parsed)
                time.sleep(0.2)
        logger.info("Extractors completed for doc=%s: %d items total", doc_id, total_updated)
        return {"entities_updated": total_updated}

    @staticmethod
    def _parse_extractor_response(response: str, key: str) -> List[Dict[str, Any]]:
        try:
            raw = response.strip()
            fence_start = raw.find("```")
            if fence_start >= 0:
                raw = raw[fence_start + 3:]
                json_marker = raw.find("json")
                if json_marker == 0:
                    raw = raw[4:]
            fence_end = raw.rfind("```")
            if fence_end >= 0:
                raw = raw[:fence_end]
            parsed = json.loads(raw.strip())
            return parsed.get(key, []) if isinstance(parsed, dict) else []
        except Exception:
            logger.warning("Failed to parse extractor response for key=%s", key)
            return []

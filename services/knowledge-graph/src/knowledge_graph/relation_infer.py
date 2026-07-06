"""Relation inference engine, adapted from sop-core socratic_loop."""

import json
import logging
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

from ai_inference.llm_client import LLMClient

from knowledge_graph.config import RelationType

logger = logging.getLogger(__name__)

RELATION_SYSTEM_PROMPT = """You are an engineering standards relationship analyst.
Given two entities found in an engineering standard, determine their relationship.

Valid relation types:
- defines: clause defines/regulates the entity
- requires: entity A depends on entity B  
- constrains: entity A limits the value/scope of entity B
- conditions_on: a condition modifies behavior of an entity
- computes_from: a calculation uses entity as input
- verifies: a verification checks the entity

Rules:
- Only infer relationships that are directly supported by the provided text
- Return a confidence score 0.0-1.0 for each relationship
- If no clear relationship, return an empty list

Format:
```json
[
  {"from": "entity A", "to": "entity B", "type": "requires", "confidence": 0.8, "evidence": "quote"},
  ...
]
```"""


class RelationInferrer:
    def __init__(self, config_name: Optional[str] = None, mode: str = "instruct"):
        self.config_name = config_name or "DeepseekV4-Flash(付费)"
        self.mode = mode

    def infer_relations(
        self,
        text: str,
        entities: List[str],
        progress_callback: Optional[Callable[[str], None]] = None,
    ) -> List[Dict[str, Any]]:
        """Infer relationships between entities based on the provided text."""
        if len(entities) < 2:
            return []

        if progress_callback:
            progress_callback(f"推理关系 {len(entities)} 个实体...")

        entity_list = ", ".join(entities[:30])
        prompt = f"""Entities: {entity_list}

Text:
{text[:8000]}

Analyze pairwise relationships between these entities based on the text. Only include relationships with clear evidence."""

        try:
            client = LLMClient()
            response = client.chat(
                messages=[
                    {"role": "system", "content": RELATION_SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                config_name=self.config_name,
                mode=self.mode,
            )
        except Exception as e:
            logger.warning("LLM call failed for relation inference: %s", e)
            return []

        return self._parse_response(response)

    def cooccurrence_relations(
        self,
        text: str,
        entities: List[str],
        within_distance: int = 200,
    ) -> List[Tuple[str, str, str, float]]:
        """Fast heuristic: entities appearing close together get a weak co-occurrence relation."""
        results: List[Tuple[str, str, str, float]] = []
        for i, e1 in enumerate(entities):
            pos1 = text.find(e1)
            if pos1 < 0:
                continue
            for e2 in entities[i + 1:]:
                pos2 = text.find(e2)
                if pos2 < 0:
                    continue
                if abs(pos1 - pos2) <= within_distance:
                    rel_type = "constrains"
                    if any(kw in e1 for kw in ["计算", "验算", "检查"]):
                        rel_type = "computes_from"
                    elif any(kw in e1 for kw in ["工况", "水位"]):
                        rel_type = "conditions_on"
                    results.append((e1, e2, rel_type, 0.1))
        return results

    def _parse_response(self, response: str) -> List[Dict[str, Any]]:
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
            if isinstance(parsed, list):
                return parsed
            return []
        except Exception:
            logger.warning("Failed to parse relation inference LLM response")
            return []

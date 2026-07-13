"""AI-driven entity extraction from evidence packets."""

import json
import logging
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

from ai_inference.llm_client import LLMClient

from knowledge_graph.config import (
    EntityLayer,
    EntitySeed,
    DEFAULT_LLM_CONFIG,
    load_seed_entities,
)

logger = logging.getLogger(__name__)

MAX_TEXT_CHARS = 8000

EXTRACT_SYSTEM_PROMPT = """You are an engineering standards analyst. Given a section of an engineering standard, extract all technical entities and their relationships to the given seed entity.

Rules:
- Extract entities (terms, parameters, conditions, actions) that appear in the text
- Classify each entity as concept (noun/term), condition (scenario/scenario), or action (calculation/verification/inspection)
- Entities must be directly supported by the text
- Return a JSON object

Format:
```json
{
  "entities": [
    {"name": "entity name", "layer": "concept|condition|action", "evidence": "quote from text"}
  ],
  "relationships": [
    {"from": "entity A", "to": "entity B", "type": "requires|constrains|conditions_on|computes_from|verifies|defines", "evidence": "quote from text"}
  ]
}
```"""


class EntityExtractor:
    def __init__(self, config_name: Optional[str] = None, mode: str = "instruct"):
        self.config_name = config_name or DEFAULT_LLM_CONFIG
        self.mode = mode
        self._seeds = load_seed_entities()
        self._seed_names: Set[str] = set()
        self._seed_aliases: Dict[str, str] = {}
        for s in self._seeds:
            self._seed_names.add(s.name)
            for a in s.aliases:
                self._seed_aliases[a] = s.name

    def find_seed_occurrences(self, text: str, seeds: Optional[List[EntitySeed]] = None) -> List[Tuple[str, int]]:
        if seeds is None:
            seeds = self._seeds
        results: List[Tuple[str, int]] = []
        for seed in seeds:
            pos = text.find(seed.name)
            if pos >= 0:
                results.append((seed.name, pos))
                continue
            for alias in seed.aliases:
                pos = text.find(alias)
                if pos >= 0:
                    results.append((seed.name, pos))
                    break
        results.sort(key=lambda x: x[1])
        return results

    def find_related_entities(
        self,
        text: str,
        seed_name: str,
        seeds: Optional[List[EntitySeed]] = None,
    ) -> List[str]:
        if seeds is None:
            seeds = self._seeds
        related: Set[str] = set()
        seed_entity = None
        for s in seeds:
            if s.name == seed_name:
                seed_entity = s
                break
        if seed_entity is None:
            return []

        all_names = set()
        for s in seeds:
            all_names.add(s.name)
            all_names.update(s.aliases)
        all_names.discard(seed_entity.name)
        for alias in seed_entity.aliases:
            all_names.discard(alias)

        for name in all_names:
            if name in text and name != seed_name:
                related.add(name)
        return list(related)

    def classify_entity(self, name: str) -> EntityLayer:
        action_patterns = ["计算", "验算", "检查", "检测", "校验", "验证", "测试"]
        condition_patterns = ["工况", "条件", "情况", "状态", "水位", "波浪", "流速", "风况", "地震"]
        for p in action_patterns:
            if p in name:
                return EntityLayer.ACTION
        for p in condition_patterns:
            if p in name:
                return EntityLayer.CONDITION
        return EntityLayer.CONCEPT

    def extract_from_packet(
        self,
        packet_text: str,
        section_path: str,
        seed_entity_names: List[str],
        progress_callback: Optional[Callable[[str], None]] = None,
    ) -> Dict[str, Any]:
        seeds_str = ", ".join(seed_entity_names[:20])
        if progress_callback:
            progress_callback(f"LLM 提取实体 [{seeds_str}]...")

        prompt = f"""Section: {section_path}
Seed Entities: {seeds_str}

Text:
{packet_text[:MAX_TEXT_CHARS]}

Extract all entities and relationships related to seed entities: "{seeds_str}"."""

        try:
            client = LLMClient()
            response = client.chat(
                messages=[
                    {"role": "system", "content": EXTRACT_SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                config_name=self.config_name,
                mode=self.mode,
            )
        except Exception as e:
            logger.warning("LLM call failed for entity extraction: %s", e)
            return {"entities": [], "relationships": []}

        return self._parse_response(response)

    def _parse_response(self, response: str) -> Dict[str, Any]:
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
            return json.loads(raw.strip())
        except Exception:
            logger.warning("Failed to parse entity extraction LLM response")
            return {"entities": [], "relationships": []}

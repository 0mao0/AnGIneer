"""Test question clustering and knowledge graph path mapping."""

import json
import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

from ai_inference.llm_client import LLMClient

from knowledge_graph.config import DEFAULT_LLM_CONFIG

logger = logging.getLogger(__name__)


@dataclass
class StructuredQuestion:
    question_id: str
    condition: str
    question: str
    answer: str
    clauses: List[str] = field(default_factory=list)
    entities: List[str] = field(default_factory=list)


QUESTION_MAP_SYSTEM_PROMPT = """You are mapping a test question onto a knowledge graph of engineering standards.

Given a question and a list of graph entities, determine:
1. Which graph entities are relevant to this question
2. The path through the graph that answers this question
3. Whether the graph's current path is consistent with the question's answer

Return JSON:
```json
{
  "relevant_entities": ["entity1", "entity2"],
  "graph_path": ["entity1", "relation_type", "entity2"],
  "consistency": "match|missing_path|contradiction",
  "new_sop_needed": false,
  "explanation": "brief explanation"
}
```"""


class QuestionMapper:
    def __init__(self, config_name: Optional[str] = None, mode: str = "instruct"):
        self.config_name = config_name or DEFAULT_LLM_CONFIG
        self.mode = mode

    def cluster_questions(
        self,
        questions: List[StructuredQuestion],
        max_clusters: int = 100,
    ) -> Dict[int, List[StructuredQuestion]]:
        """Cluster questions by condition+answer signature hash."""
        clusters: Dict[int, List[StructuredQuestion]] = {}
        for q in questions:
            sig = self._question_signature(q)
            bucket = hash(sig) % max_clusters
            if bucket not in clusters:
                clusters[bucket] = []
            clusters[bucket].append(q)
        return clusters

    def select_representatives(
        self,
        questions: List[StructuredQuestion],
        max_per_cluster: int = 3,
    ) -> List[StructuredQuestion]:
        """Select representative questions from a cluster (longest = most informative)."""
        if len(questions) <= max_per_cluster:
            return questions
        sorted_qs = sorted(questions, key=lambda q: len(q.question) + len(q.answer), reverse=True)
        return sorted_qs[:max_per_cluster]

    def extract_entities_from_question(self, question: StructuredQuestion) -> List[str]:
        """Simple keyword extraction from question text using known entity patterns."""
        known_terms = [
            "航道", "港池", "码头", "防波堤", "护岸", "边坡", "地基",
            "设计高水位", "设计低水位", "极端高水位", "极端低水位",
            "乘潮水位", "设计波高", "设计流速", "地震工况",
            "承载力", "抗倾覆", "抗滑移", "沉降", "稳定性",
            "设计船型", "通航宽度", "设计水深", "安全系数",
            "冬季", "防冻", "疏浚", "回淤",
        ]
        text = f"{question.condition} {question.question} {question.answer}"
        found = []
        for term in known_terms:
            if term in text:
                found.append(term)
        return found

    def map_to_graph(
        self,
        question: StructuredQuestion,
        graph_entities: List[str],
        progress_callback: Optional[Callable[[str], None]] = None,
    ) -> Dict[str, Any]:
        """Use LLM to map a question to a path through the knowledge graph."""
        if progress_callback:
            progress_callback(f"映射题目 {question.question_id}...")

        entities_text = ", ".join(graph_entities[:50])
        prompt = f"""Question: {question.question}
Condition: {question.condition}
Answer: {question.answer}
Clauses: {", ".join(question.clauses)}

Available Graph Entities:
{entities_text}

Map this question to the graph. Does a path exist? Is it consistent?"""

        try:
            client = LLMClient()
            response = client.chat(
                messages=[
                    {"role": "system", "content": QUESTION_MAP_SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                config_name=self.config_name,
                mode=self.mode,
            )
        except Exception as e:
            logger.warning("LLM call failed for question mapping: %s", e)
            return {"relevant_entities": [], "graph_path": [], "consistency": "error", "new_sop_needed": False, "explanation": str(e)}

        return self._parse_response(response)

    def _question_signature(self, question: StructuredQuestion) -> str:
        parts = [question.condition.strip(), question.answer.strip()[:100]]
        return "||".join(parts)

    def _build_path_signature(self, path: List[str]) -> str:
        return "::".join(path)

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
            logger.warning("Failed to parse question mapping LLM response")
            return {"relevant_entities": [], "graph_path": [], "consistency": "error", "new_sop_needed": False, "explanation": "parse failed"}

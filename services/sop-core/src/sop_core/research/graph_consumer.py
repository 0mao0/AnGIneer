"""Graph Consumer: bridges knowledge-graph output to sop-core SOP loading.

Consumes entities and path data from knowledge-graph and produces SOP definitions
compatible with data/sops/json/*.json format for sop-core execution.
"""

import json
import logging
import os
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class GraphConsumer:
    """Consumes knowledge graph data to produce executable SOPs."""

    def __init__(self, graph_store=None):
        self._graph_store = graph_store

    def consume_path_to_sop(
        self,
        path_entities: List[str],
        sop_title: str,
        source_clause: str = "",
    ) -> Dict[str, Any]:
        """Convert a graph path into an SOP JSON definition."""
        blackboard_inputs = []
        blackboard_outputs = []

        for entity in path_entities[:-1]:
            if any(kw in entity for kw in ["计算", "验算", "检查"]):
                blackboard_outputs.append(f"{entity}结果")
            else:
                blackboard_inputs.append(entity)

        last_entity = path_entities[-1] if path_entities else ""
        if last_entity:
            blackboard_outputs.append(f"{last_entity}结果")

        sop = {
            "id": sop_title,
            "name_zh": sop_title,
            "name_en": sop_title,
            "description": f"根据 {source_clause} 自动生成 (via knowledge-graph)",
            "_source": "knowledge_graph",
            "source_clause": source_clause,
            "blackboard": {
                "required": blackboard_inputs,
                "outputs": blackboard_outputs,
                "all": blackboard_inputs + blackboard_outputs,
            },
            "steps": [],
        }

        for i, entity in enumerate(path_entities):
            step = {
                "step": i + 1,
                "type": "inspection" if i == 0 else "calculation",
                "description": f"{entity} — 依据 {source_clause}",
                "tools": [],
                "inputs": {},
                "outputs": {},
            }
            sop["steps"].append(step)

        return sop

    def save_sop_to_json(
        self,
        sop: Dict[str, Any],
        output_dir: str,
    ) -> str:
        """Save an SOP definition to a JSON file."""
        os.makedirs(output_dir, exist_ok=True)
        sop_id = sop.get("id", "unknown")
        filename = f"{sop_id}.json"
        filepath = os.path.join(output_dir, filename)
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(sop, f, ensure_ascii=False, indent=2)
        logger.info("Saved SOP: %s", filepath)
        return filepath

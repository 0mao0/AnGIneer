"""Generate SOP definitions from knowledge graph paths."""

import uuid
from typing import Any, Dict, List, Optional

from knowledge_graph.config import EntityLayer


class SopPathGenerator:
    LAYER_TO_STEP_TYPE = {
        EntityLayer.CONCEPT: "inspection",
        EntityLayer.CONDITION: "decision",
        EntityLayer.ACTION: "calculation",
    }

    def path_to_sop_template(
        self,
        path: List[Dict[str, Any]],
        source_clause: str = "",
    ) -> Dict[str, Any]:
        """Convert a graph path into an SOP template compatible with data/sops/json/*.json format."""
        merged_path = self._merge_concept_nodes(path)

        steps = []
        for i, node in enumerate(merged_path):
            if isinstance(node, dict) and "name" in node:
                step = self._node_to_step(node, i + 1, source_clause)
                steps.append(step)

        sop_id = self._derive_sop_id(path, source_clause)
        title = self._derive_sop_title(path)

        blackboard_inputs = []
        blackboard_outputs = []
        for node in merged_path:
            if isinstance(node, dict) and node.get("layer") == EntityLayer.CONCEPT:
                blackboard_inputs.append(node["name"])
            elif isinstance(node, dict) and node.get("layer") == EntityLayer.ACTION:
                blackboard_outputs.append(f"{node['name']}结果")

        return {
            "id": sop_id,
            "name_zh": title,
            "name_en": title,
            "description": f"根据 {source_clause} 自动生成",
            "source_clause": source_clause,
            "blackboard": {
                "required": list(dict.fromkeys(blackboard_inputs)),
                "outputs": blackboard_outputs,
                "all": list(dict.fromkeys(blackboard_inputs + blackboard_outputs)),
            },
            "steps": steps,
        }

    def generate_sop_skeleton(
        self,
        sop_id: str,
        title: str,
        path_entities: List[str],
        entities: Dict[str, EntityLayer],
        source_clause: str = "",
    ) -> Dict[str, Any]:
        """Generate a minimal SOP skeleton from a linear entity path."""
        path = []
        for i, entity_name in enumerate(path_entities):
            path.append({
                "name": entity_name,
                "layer": entities.get(entity_name, EntityLayer.CONCEPT),
            })
            if i < len(path_entities) - 1:
                next_entity = path_entities[i + 1]
                next_layer = entities.get(next_entity, EntityLayer.CONCEPT)
                if next_layer == EntityLayer.ACTION:
                    rel = "computes_from"
                elif next_layer == EntityLayer.CONDITION:
                    rel = "conditions_on"
                else:
                    rel = "constrains"
                path.append({"relation": rel})

        sop = self.path_to_sop_template(path, source_clause)
        sop["id"] = sop_id
        sop["name_zh"] = title
        sop["name_en"] = title
        return sop

    def _node_to_step(self, node: Dict[str, Any], index: int, clause: str) -> Dict[str, Any]:
        step_type = self.LAYER_TO_STEP_TYPE.get(node.get("layer", EntityLayer.CONCEPT), "inspection")
        return {
            "step": index,
            "type": step_type,
            "description": f"{node.get('name', '')} — 依据 {clause}",
            "tools": [],
            "inputs": {},
            "outputs": {},
        }

    def _merge_concept_nodes(self, path: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Merge adjacent concept-only nodes into a single normalized-computes_from-action chain."""
        result = []
        pending_concepts = []
        for node in path:
            if isinstance(node, dict) and "relation" in node:
                pending_concepts.append(node)
            elif isinstance(node, dict) and "name" in node:
                if node.get("layer") == EntityLayer.ACTION:
                    if pending_concepts:
                        result.extend(pending_concepts)
                        pending_concepts = []
                    result.append(node)
                else:
                    if pending_concepts:
                        result.append(pending_concepts[-1])
                        pending_concepts = pending_concepts[:-1]
                    pending_concepts.append(node)
            else:
                result.append(node)
        if pending_concepts:
            result.append(pending_concepts[-1])
        return result

    def _derive_sop_id(self, path: List[Dict[str, Any]], clause: str) -> str:
        entity_names = [n["name"] for n in path if isinstance(n, dict) and "name" in n]
        if entity_names:
            return entity_names[-1]
        return uuid.uuid4().hex[:8]

    def _derive_sop_title(self, path: List[Dict[str, Any]]) -> str:
        entity_names = [n["name"] for n in path if isinstance(n, dict) and "name" in n]
        return entity_names[-1] if entity_names else "SOP"

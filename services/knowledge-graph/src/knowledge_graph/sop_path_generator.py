import json
import os
import uuid
from typing import Any, Dict, List, Optional

from knowledge_graph.config import EntityLayer, DEFAULT_LLM_CONFIG
from knowledge_graph.graph_store import GraphStore

SOP_GENERATION_SYSTEM_PROMPT = """你是工程标准 SOP 生成器。你的任务是根据知识图谱提取出的框架步骤、设计原则、注意事项和计算案例，生成一份完整的、可直接执行的 SOP。

输入信息包括：
1. 框架步骤序列（必做）
2. 每个步骤关联的设计原则（必须遵守的规范要求）
3. 每个步骤关联的注意事项/反例（常见错误）
4. 每个步骤关联的计算案例（参考计算过程）
5. 参考 SOP（格式参考）

输出要求：
- 每个步骤必须有唯一的 id（如 step_1, step_2）
- 每个步骤的 name 应简短描述该步骤做什么
- execution.tool 根据步骤类型选择：calculator（计算）、table_lookup（查表）、manual（查询/收集信息）、conditional（if/else 判断）
- execution.inputs 和 execution.outputs 列出输入/输出变量名及其描述
- next_step_id 指向下一步（最后一步可以为 null）
- 步骤可以直接列出来，无需考虑分支走向。如果有分支，用 conditional 类型并列出分支走向。
- description 写清楚具体的操作、引用的规范条款号、必要的公式
- 参考规范中的章节号，如果相关则引用

输出格式：
```json
{
  "name_zh": "SOP中文名称",
  "description": "该SOP功能简要描述",
  "steps": [
    {
      "id": "step_1",
      "name": "步骤名称",
      "description": "具体操作说明，含规范条款号",
      "execution": {
        "tool": "calculator",
        "inputs": {"变量名": "变量说明"},
        "outputs": {"变量名": "结果说明"}
      },
      "next_step_id": "step_2"
    }
  ],
  "blackboard": {
    "required": ["输入变量1", "输入变量2"],
    "outputs": ["输出变量1"]
  }
}
```

请只输出 JSON，不要输出其他内容。"""

SOP_GENERATION_USER_TEMPLATE = """请根据以下信息生成一个完整的工程 SOP。

【框架名称】: {framework_name}
【来源章节】: {source_section}
【框架步骤序列】:
{framework_steps}

{principles_text}

{warnings_text}

{examples_text}

{reference_sops}

请为上述框架生成一个完整、可执行的 SOP。确保：
1. 每个步骤有明确的 tool 类型和输入/输出
2. description 包含具体操作和规范条款号
3. 变量名保持中文，便于工程师理解
4. 步骤数量应与框架步骤保持一致
"""


class SopPathGenerator:
    LAYER_TO_STEP_TYPE = {
        EntityLayer.CONCEPT: "inspection",
        EntityLayer.CONDITION: "decision",
        EntityLayer.ACTION: "calculation",
    }

    def __init__(self, store: Optional[GraphStore] = None, config_name: Optional[str] = None):
        self.store = store
        self.config_name = config_name or DEFAULT_LLM_CONFIG

    def path_to_sop_template(
        self,
        path: List[Dict[str, Any]],
        source_clause: str = "",
        library_id: str = "",
        doc_id: str = "",
    ) -> Dict[str, Any]:
        merged_path = self._merge_concept_nodes(path)

        steps = []
        for i, node in enumerate(merged_path):
            if isinstance(node, dict) and "name" in node:
                step = self._node_to_step(node, i + 1, source_clause)
                step = self._enrich_step_with_extractions(step, node, library_id, doc_id)
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

        if self.store:
            frameworks = self.store.get_frameworks_by_doc(library_id or "", doc_id or "")
            if frameworks:
                matches = []
                for fw in frameworks:
                    fw_steps = json.loads(fw.steps_json)
                    if fw_steps and steps and fw_steps[0] == steps[0].get("name_zh", ""):
                        matches.append(fw)
                if matches:
                    steps_concat = " → ".join(json.loads(matches[0].steps_json))
                    description = self._get_sop_description(path, source_clause) + f"\n框架流程: {steps_concat}"
                else:
                    description = self._get_sop_description(path, source_clause)
            else:
                description = self._get_sop_description(path, source_clause)
        else:
            description = self._get_sop_description(path, source_clause)

        return {
            "id": sop_id,
            "name_zh": title,
            "name_en": title,
            "description": description,
            "source_clause": source_clause,
            "library_id": library_id,
            "doc_id": doc_id,
            "blackboard": {
                "required": list(dict.fromkeys(blackboard_inputs)),
                "outputs": blackboard_outputs,
                "all": list(dict.fromkeys(blackboard_inputs + blackboard_outputs)),
            },
            "steps": steps,
        }

    def _get_sop_description(self, path: List[Dict[str, Any]], clause: str) -> str:
        entity_names = [n["name"] for n in path if isinstance(n, dict) and "name" in n]
        return f"根据 {clause} 自动生成。涉及实体: {' → '.join(entity_names)}"

    def _enrich_step_with_extractions(self, step: Dict[str, Any], node: Dict[str, Any], library_id: str, doc_id: str) -> Dict[str, Any]:
        if not self.store or not library_id or not doc_id:
            return step
        name = node.get("name", "")
        entity = self.store.get_entity_by_name(name)
        if not entity:
            return step

        entity_desc = entity.description
        entity_aliases = entity.aliases
        desc_parts = [step.get("description", "")]
        if entity_desc:
            desc_parts.append(f"📖 {entity_desc}")

        principles = self.store.get_principles_by_entity_ids([entity.entity_id])
        warnings = self.store.get_warnings_by_entity_ids([entity.entity_id])
        examples = self.store.get_examples_by_entity_ids([entity.entity_id])

        if principles:
            principle_lines = []
            for p in principles:
                label = {"mandatory": "强制", "recommended": "推荐", "constraint": "限制"}.get(p.category, p.category)
                principle_lines.append(f"✅ [{label}] {p.principle_text} ({p.source_clause})")
            desc_parts.append("原则:\n" + "\n".join(principle_lines))
            step["principles"] = [{"principle_id": p.principle_id, "principle_text": p.principle_text,
                                   "category": p.category, "source_clause": p.source_clause} for p in principles]

        if warnings:
            warning_lines = []
            for w in warnings:
                severity_icon = {"safety": "🚨", "economic": "💰", "quality": "⚠️"}.get(w.severity, "⚠️")
                warning_lines.append(f"{severity_icon} {w.warning_text} ({w.source_section})")
            desc_parts.append("反例/注意:\n" + "\n".join(warning_lines))
            step["warnings"] = [{"warning_id": w.warning_id, "warning_text": w.warning_text,
                                  "severity": w.severity, "source_section": w.source_section} for w in warnings]

        if examples:
            example_lines = []
            for ex in examples:
                example_lines.append(f"📋 {ex.title}")
                if ex.computation_text:
                    example_lines.append(f"  计算: {ex.computation_text[:100]}")
                if ex.inputs_json and ex.inputs_json != "{}":
                    try:
                        inputs = json.loads(ex.inputs_json)
                        example_lines.append(f"  输入: {json.dumps(inputs, ensure_ascii=False)}")
                    except (json.JSONDecodeError, TypeError):
                        pass
            desc_parts.append("案例:\n" + "\n".join(example_lines))
            step["examples"] = [{"example_id": ex.example_id, "title": ex.title,
                                  "computation_text": ex.computation_text, "inputs_json": ex.inputs_json} for ex in examples]

        if entity_aliases:
            desc_parts.append(f"别名: {', '.join(entity_aliases)}")

        step["description"] = "\n---\n".join(desc_parts)
        return step

    def generate_sop_skeleton(
        self,
        sop_id: str,
        title: str,
        path_entities: List[str],
        entities: Dict[str, EntityLayer],
        source_clause: str = "",
        library_id: str = "",
        doc_id: str = "",
    ) -> Dict[str, Any]:
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

        sop = self.path_to_sop_template(path, source_clause, library_id, doc_id)
        sop["id"] = sop_id
        sop["name_zh"] = title
        sop["name_en"] = title
        return sop

    def _existing_sop_names(self) -> set:
        """Return set of name_zh from existing SOP JSON files."""
        sop_dir = self._sop_json_dir()
        names = set()
        if not os.path.exists(sop_dir):
            return names
        for fname in os.listdir(sop_dir):
            if not fname.endswith(".json"):
                continue
            try:
                with open(os.path.join(sop_dir, fname), "r", encoding="utf-8") as f:
                    data = json.load(f)
                name = data.get("name_zh", "") or data.get("name_en", "")
                if name:
                    names.add(name)
            except Exception:
                continue
        return names

    def _sop_json_dir(self) -> str:
        return os.path.join(os.environ.get("DATA_DIR", "data"), "sops", "json")

    def _load_reference_sops(self, limit: int = 3) -> List[Dict[str, Any]]:
        """Load existing SOPs as reference examples, preferring well-structured ones."""
        sop_dir = self._sop_json_dir()
        refs = []
        if not os.path.exists(sop_dir):
            return refs
        for fname in os.listdir(sop_dir):
            if not fname.endswith(".json") or len(refs) >= limit:
                break
            try:
                with open(os.path.join(sop_dir, fname), "r", encoding="utf-8") as f:
                    data = json.load(f)
                steps = data.get("steps", [])
                if steps and any(s.get("execution") and s["execution"].get("tool") for s in steps):
                    refs.append(data)
            except Exception:
                continue
        return refs

    def _format_reference_sops(self, refs: List[Dict[str, Any]], max_steps: int = 3) -> str:
        """Format reference SOPs as prompt context."""
        if not refs:
            return ""
        lines = ["【参考SOP - 格式和风格示例】:"]
        for i, ref in enumerate(refs):
            name = ref.get("name_zh", ref.get("name_en", f"SOP_{i+1}"))
            lines.append(f"\n参考SOP {i+1}: {name}")
            desc = ref.get("description", "")
            if isinstance(desc, dict):
                desc = desc.get("content", "")
            lines.append(f"  描述: {desc[:200]}")
            for j, step in enumerate(ref.get("steps", [])[:max_steps]):
                sname = step.get("name", step.get("name_zh", ""))
                tool = (step.get("execution") or {}).get("tool", "manual")
                sid = step.get("id", f"step_{j+1}")
                lines.append(f"  步骤: {sid}={sname} (tool={tool})")
            lines.append("  ...")
        return "\n".join(lines)

    def _gather_step_enrichments(self, step_names: List[str]) -> Dict[str, Any]:
        """Gather principles, warnings, examples for each step entity."""
        principles_by_step = {}
        warnings_by_step = {}
        examples_by_step = {}

        if not self.store:
            return {"principles": principles_by_step, "warnings": warnings_by_step, "examples": examples_by_step}

        for name in step_names:
            entity = self.store.get_entity_by_name(name)
            if not entity:
                continue

            prs = self.store.get_principles_by_entity_ids([entity.entity_id])
            if prs:
                principles_by_step[name] = [
                    {"text": p.principle_text, "category": p.category, "source": p.source_clause}
                    for p in prs
                ]

            wns = self.store.get_warnings_by_entity_ids([entity.entity_id])
            if wns:
                warnings_by_step[name] = [
                    {"text": w.warning_text, "severity": w.severity, "source": w.source_section}
                    for w in wns
                ]

            exs = self.store.get_examples_by_entity_ids([entity.entity_id])
            if exs:
                examples_by_step[name] = [
                    {"title": ex.title, "computation": ex.computation_text, "inputs": ex.inputs_json}
                    for ex in exs
                ]

        return {"principles": principles_by_step, "warnings": warnings_by_step, "examples": examples_by_step}

    def _format_enrichments_for_prompt(self, enrichments: Dict[str, Any], step_names: List[str]) -> tuple:
        """Format enrichments as prompt sections."""
        principles_text = ""
        warnings_text = ""
        examples_text = ""

        pr_by_step = enrichments.get("principles", {})
        if pr_by_step:
            lines = ["【设计原则 - 每个步骤必须遵守的规范要求】:"]
            for name in step_names:
                if name in pr_by_step:
                    lines.append(f"\n{name}步骤相关原则:")
                    for p in pr_by_step[name]:
                        cat_label = {"mandatory": "强制", "recommended": "推荐", "constraint": "限制"}.get(p["category"], p["category"])
                        lines.append(f"  [{cat_label}] {p['text']} (来源: {p['source']})")
            principles_text = "\n".join(lines)

        wa_by_step = enrichments.get("warnings", {})
        if wa_by_step:
            lines = ["\n【注意事项/常见错误】:"]
            for name in step_names:
                if name in wa_by_step:
                    lines.append(f"\n{name}步骤注意事项:")
                    for w in wa_by_step[name]:
                        lines.append(f"  [{w['severity']}] {w['text']} (来源: {w['source']})")
            warnings_text = "\n".join(lines)

        ex_by_step = enrichments.get("examples", {})
        if ex_by_step:
            lines = ["\n【计算案例参考】:"]
            for name in step_names:
                if name in ex_by_step:
                    lines.append(f"\n{name}步骤案例:")
                    for ex in ex_by_step[name]:
                        lines.append(f"  案例: {ex['title']}")
                        if ex["computation"]:
                            lines.append(f"  计算过程: {ex['computation'][:200]}")
            examples_text = "\n".join(lines)

        return principles_text, warnings_text, examples_text

    def _generate_sop_via_llm(
        self, framework_name: str, fw_steps: List[str], source_section: str,
        library_id: str, doc_id: str,
    ) -> Optional[Dict[str, Any]]:
        """Use LLM to generate a complete SOP from framework data."""
        try:
            from ai_inference.llm_client import LLMClient
        except ImportError:
            return None

        enrichments = self._gather_step_enrichments(fw_steps)
        principles_text, warnings_text, examples_text = self._format_enrichments_for_prompt(enrichments, fw_steps)
        refs = self._load_reference_sops()
        ref_text = self._format_reference_sops(refs)

        steps_text = "\n".join(f"{i+1}. {s}" for i, s in enumerate(fw_steps))
        user_prompt = SOP_GENERATION_USER_TEMPLATE.format(
            framework_name=framework_name,
            source_section=source_section or "全文",
            framework_steps=steps_text,
            principles_text=principles_text,
            warnings_text=warnings_text,
            examples_text=examples_text,
            reference_sops=ref_text,
        )

        try:
            client = LLMClient()
            response = client.chat(
                messages=[
                    {"role": "system", "content": SOP_GENERATION_SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                config_name=self.config_name,
                mode="instruct",
                max_tokens=4096,
            )
            parsed = self._parse_sop_response(response)
            if parsed and parsed.get("steps"):
                return parsed
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning("LLM SOP generation failed for %s: %s", framework_name, e)

        return None

    def _parse_sop_response(self, response: str) -> Optional[Dict[str, Any]]:
        """Parse LLM response into SOP dict."""
        if not response:
            return None
        text = response.strip()
        for marker in ["```json", "```"]:
            if marker in text:
                start = text.find(marker) + len(marker)
                end = text.rfind("```")
                if end > start:
                    text = text[start:end].strip()
                break
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            try:
                start = text.find("{")
                end = text.rfind("}") + 1
                if start >= 0 and end > start:
                    return json.loads(text[start:end])
            except (json.JSONDecodeError, ValueError):
                pass
        return None

    def generate_sops_from_doc(self, library_id: str, doc_id: str, store: GraphStore) -> Dict[str, Any]:
        self.store = store
        existing_names = self._existing_sop_names()
        frameworks = store.get_frameworks_by_doc(library_id, doc_id)
        generated = []

        if not frameworks:
            all_entities = store.list_entities_by_doc(library_id, doc_id)
            action_entities = [e for e in all_entities if e.layer == EntityLayer.ACTION]
            seen = set()
            for ae in action_entities:
                incoming = store.get_relations_by_entity(ae.entity_id, direction="incoming")
                incoming = [r for r in incoming if r.library_id == library_id and r.doc_id == doc_id]
                path = [ae.name]
                current_id = ae.entity_id
                depth = 0
                while depth < 8:
                    rels = store.get_relations_by_entity(current_id, direction="incoming")
                    rels = [r for r in rels if r.library_id == library_id and r.doc_id == doc_id]
                    if not rels:
                        break
                    prev = store.get_entity(rels[0].source_id)
                    if not prev or prev.name in path:
                        break
                    path.insert(0, prev.name)
                    current_id = prev.entity_id
                    depth += 1
                path_key = "\u2192".join(path)
                if path_key in seen or len(path) < 2:
                    continue
                seen.add(path_key)
                if path[-1] in existing_names:
                    continue
                entities_map = {}
                for step_name in path:
                    entity = store.get_entity_by_name(step_name)
                    entities_map[step_name] = entity.layer if entity else EntityLayer.CONCEPT
                sop = self.generate_sop_skeleton(
                    sop_id=uuid.uuid4().hex[:8],
                    title=path[-1],
                    path_entities=path,
                    entities=entities_map,
                    library_id=library_id,
                    doc_id=doc_id,
                )
                generated.append(sop)
        else:
            for fw in frameworks:
                fw_steps = json.loads(fw.steps_json) if fw.steps_json else []
                if not fw_steps:
                    continue
                if fw.name in existing_names:
                    continue

                llm_sop = self._generate_sop_via_llm(
                    framework_name=fw.name,
                    fw_steps=fw_steps,
                    source_section=fw.source_section or "",
                    library_id=library_id,
                    doc_id=doc_id,
                )

                if llm_sop:
                    sop_id = fw.framework_id or uuid.uuid4().hex[:8]
                    llm_sop["id"] = sop_id
                    if "library_id" not in llm_sop:
                        llm_sop["library_id"] = library_id
                    if "doc_id" not in llm_sop:
                        llm_sop["doc_id"] = doc_id
                    for step in llm_sop.get("steps", []):
                        if "type" in step and "step" not in step:
                            step["step"] = step.pop("type")
                    generated.append(llm_sop)
                else:
                    entities_map = {}
                    for step_name in fw_steps:
                        entity = store.get_entity_by_name(step_name)
                        entities_map[step_name] = entity.layer if entity else EntityLayer.CONCEPT
                    sop_id = fw.framework_id or uuid.uuid4().hex[:8]
                    sop = self.generate_sop_skeleton(
                        sop_id=sop_id,
                        title=fw.name,
                        path_entities=fw_steps,
                        entities=entities_map,
                        source_clause=fw.source_section or "",
                        library_id=library_id,
                        doc_id=doc_id,
                    )
                    generated.append(sop)

        self._write_sops_to_disk(generated, library_id)
        return {"generated": [s["id"] for s in generated], "total": len(generated)}

    def _write_sops_to_disk(self, sops: List[Dict[str, Any]], library_id: str) -> None:
        sop_dir = os.path.join(os.environ.get("DATA_DIR", "data"), "sops", "json")
        index_dir = os.path.join(os.environ.get("DATA_DIR", "data"), "sops")
        os.makedirs(sop_dir, exist_ok=True)
        for sop in sops:
            sop_path = os.path.join(sop_dir, f"{sop['id']}.json")
            with open(sop_path, "w", encoding="utf-8") as f:
                json.dump(sop, f, ensure_ascii=False, indent=2)
        index_path = os.path.join(index_dir, "index.json")
        if os.path.exists(index_path):
            with open(index_path, "r", encoding="utf-8") as f:
                raw = json.load(f)
            if isinstance(raw, dict):
                index_data = raw
            else:
                index_data = {"sops": raw if isinstance(raw, list) else []}
        else:
            index_data = {"sops": []}
        existing_ids = {s["id"] for s in index_data.get("sops", [])}
        for sop in sops:
            if sop["id"] not in existing_ids:
                index_data.setdefault("sops", []).append({
                    "id": sop["id"],
                    "name_zh": sop["name_zh"],
                    "library_id": library_id,
                })
        with open(index_path, "w", encoding="utf-8") as f:
            json.dump(index_data, f, ensure_ascii=False, indent=2)

    def _node_to_step(self, node: Dict[str, Any], index: int, clause: str) -> Dict[str, Any]:
        step_type = self.LAYER_TO_STEP_TYPE.get(node.get("layer", EntityLayer.CONCEPT), "inspection")
        return {
            "id": uuid.uuid4().hex[:8],
            "step": index,
            "type": step_type,
            "name_zh": node.get("name", ""),
            "description": f"{node.get('name', '')} — 依据 {clause}",
            "tools": [],
            "inputs": {},
            "outputs": {},
        }

    def _merge_concept_nodes(self, path: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
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
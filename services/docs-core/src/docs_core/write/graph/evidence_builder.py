"""Build evidence packets from document content for entity extraction."""

import re
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class EvidencePacket:
    packet_id: str
    library_id: str
    doc_id: str
    doc_title: str = ""
    section_path: str = ""
    block_ids: List[str] = field(default_factory=list)
    summary_text: str = ""
    raw_text: str = ""
    entities: List[str] = field(default_factory=list)
    conditions: List[str] = field(default_factory=list)
    formulas: List[str] = field(default_factory=list)
    tables: List[str] = field(default_factory=list)
    citations: List[Dict[str, Any]] = field(default_factory=list)


def _parse_sections(document_content: str) -> List[tuple]:
    """Split document_content into (heading_text, body_text) pairs."""
    lines = document_content.split("\n")
    sections: List[tuple] = []
    current_heading = ""
    current_lines: List[str] = []

    for line in lines:
        m = re.match(r"^(#{1,6})\s+(.+)$", line)
        if m:
            if current_heading or current_lines:
                sections.append((current_heading, "\n".join(current_lines).strip()))
            current_heading = m.group(2).strip()
            current_lines = []
        else:
            current_lines.append(line)

    if current_heading or current_lines:
        sections.append((current_heading, "\n".join(current_lines).strip()))

    return sections


def _heading_char_positions(document_content: str) -> List[int]:
    """Return character offsets where markdown headings start."""
    return [m.start() for m in re.finditer(r"^#{1,6}\s+", document_content, re.MULTILINE)]


def _assign_items_to_sections(
    structured_items: List[Dict[str, Any]],
    sections: List[tuple],
    document_content: str,
) -> List[List[Dict[str, Any]]]:
    """Assign each structured_item to the section it belongs to.

    Priority:
      1. section_path on the item
      2. heading-type items group following items
      3. content-position fallback
    """
    result: List[List[Dict[str, Any]]] = [[] for _ in sections]

    if not structured_items:
        return result

    if len(sections) <= 1:
        result[0] = list(structured_items)
        return result

    # Phase 1 — items with explicit section_path
    remaining: List[Dict[str, Any]] = []
    for item in structured_items:
        item_path = (item.get("section_path") or "").strip()
        if item_path:
            placed = False
            for sec_idx, (sec_heading, _) in enumerate(sections):
                if sec_heading == item_path:
                    result[sec_idx].append(item)
                    placed = True
                    break
            if placed:
                continue
        remaining.append(item)

    # Phase 2 — heading-group matching
    heading_groups: List[tuple] = []
    current_heading = ""
    current_group: List[Dict[str, Any]] = []
    has_heading_items = False

    for item in remaining:
        if item.get("type") == "heading":
            has_heading_items = True
            if current_heading or current_group:
                heading_groups.append((current_heading, current_group))
            current_heading = (item.get("content") or "").strip()
            current_group = [item]
        else:
            current_group.append(item)

    if current_heading or current_group:
        heading_groups.append((current_heading, current_group))

    if has_heading_items:
        used: set = set()

        for sec_idx, (sec_heading, _) in enumerate(sections):
            if not sec_heading:
                continue
            for g_idx, (grp_heading, grp_items) in enumerate(heading_groups):
                if g_idx in used:
                    continue
                if grp_heading == sec_heading:
                    result[sec_idx] = grp_items
                    used.add(g_idx)
                    break

        for g_idx, (grp_heading, grp_items) in enumerate(heading_groups):
            if g_idx not in used and not grp_heading:
                result[0].extend(grp_items)
                used.add(g_idx)

        for g_idx, (grp_heading, grp_items) in enumerate(heading_groups):
            if g_idx in used:
                continue
            placed = False
            for sec_idx, (sec_heading, _) in enumerate(sections):
                if sec_heading == grp_heading:
                    result[sec_idx].extend(grp_items)
                    used.add(g_idx)
                    placed = True
                    break
            if not placed:
                target = 0
                for sec_idx, (_, content) in enumerate(sections):
                    if content:
                        target = sec_idx
                        break
                result[target].extend(grp_items)

        return result

    # Phase 3 — content-position fallback
    heading_positions = _heading_char_positions(document_content)
    section_ranges = list(
        zip(
            heading_positions,
            list(heading_positions[1:]) + [len(document_content)],
        )
    )

    for item in remaining:
        assigned = False

        item_content = item.get("content") or ""
        if item_content:
            pos = document_content.find(item_content)
            if pos >= 0:
                for idx, (start, end) in enumerate(section_ranges):
                    if start <= pos < end:
                        result[idx].append(item)
                        assigned = True
                        break
            if assigned:
                continue

        for idx, (heading, content) in enumerate(sections):
            if content and (not item_content or item_content in content):
                result[idx].append(item)
                assigned = True
                break

        if not assigned:
            target = 0
            for idx, (_, content) in enumerate(sections):
                if content:
                    target = idx
                    break
            result[target].append(item)

    return result


def _extract_item_fields(
    items: List[Dict[str, Any]],
) -> tuple:
    """Extract block_ids, tables, formulas, entities, conditions from items."""
    block_ids: List[str] = []
    tables: List[str] = []
    formulas: List[str] = []
    entities: List[str] = []
    conditions: List[str] = []

    for item in items:
        item_id = item.get("id")
        if item_id:
            block_ids.append(item_id)

        if item.get("type") == "table":
            tables.append(item.get("content") or "")

        formula_val = item.get("formula") or (item.get("content") or "" if item.get("type") == "formula" else "")
        if formula_val:
            formulas.append(formula_val)

        item_entities = item.get("entities")
        if isinstance(item_entities, list):
            entities.extend(item_entities)

        item_conditions = item.get("conditions")
        if isinstance(item_conditions, list):
            conditions.extend(item_conditions)

    return block_ids, tables, formulas, entities, conditions


def _split_oversized_section(
    content: str,
    heading: str,
    library_id: str,
    doc_id: str,
    doc_title: str,
    block_ids: List[str],
    entities: List[str],
    conditions: List[str],
    formulas: List[str],
    tables: List[str],
    max_chars: int,
) -> List[EvidencePacket]:
    """Split section content exceeding max_chars into multiple packets."""
    paragraphs = [p.strip() for p in content.split("\n\n") if p.strip()]
    if not paragraphs:
        paragraphs = [content]

    packets: List[EvidencePacket] = []
    current_chunk = ""

    for para in paragraphs:
        if current_chunk and (len(current_chunk) + len(para) + 2 > max_chars):
            packets.append(
                EvidencePacket(
                    packet_id=uuid.uuid4().hex[:12],
                    library_id=library_id,
                    doc_id=doc_id,
                    doc_title=doc_title,
                    section_path=heading,
                    block_ids=list(block_ids),
                    raw_text=current_chunk.strip(),
                    entities=list(set(entities)),
                    conditions=list(set(conditions)),
                    formulas=list(formulas),
                    tables=list(tables),
                )
            )
            current_chunk = ""
        current_chunk += para + "\n\n"

    if current_chunk.strip():
        packets.append(
            EvidencePacket(
                packet_id=uuid.uuid4().hex[:12],
                library_id=library_id,
                doc_id=doc_id,
                doc_title=doc_title,
                section_path=heading,
                block_ids=list(block_ids),
                raw_text=current_chunk.strip(),
                entities=list(set(entities)),
                conditions=list(set(conditions)),
                formulas=list(formulas),
                tables=list(tables),
            )
        )

    return packets


def build_evidence_packets(
    *,
    library_id: str,
    doc_id: str,
    doc_title: str,
    document_content: str,
    structured_items: List[Dict[str, Any]],
    doc_blocks_graph: Optional[Dict[str, Any]] = None,
    max_chars_per_packet: int = 20000,
) -> List[EvidencePacket]:
    sections = _parse_sections(document_content)
    section_items = _assign_items_to_sections(structured_items, sections, document_content)

    packets: List[EvidencePacket] = []

    acc_headings: List[str] = []
    acc_text_parts: List[str] = []
    acc_items: List[Dict[str, Any]] = []
    acc_size = 0

    def _flush_acc() -> None:
        nonlocal acc_headings, acc_text_parts, acc_items, acc_size
        if not acc_text_parts:
            return
        joined = "\n\n".join(
            (f"# {h}\n" if h else "") + t for h, t in zip(acc_headings, acc_text_parts)
        )
        block_ids, tables, formulas, entities, conditions = _extract_item_fields(acc_items)
        seen = set()
        ordered_paths = [h for h in acc_headings if not (h in seen or seen.add(h))]
        packets.append(
            EvidencePacket(
                packet_id=uuid.uuid4().hex[:12],
                library_id=library_id,
                doc_id=doc_id,
                doc_title=doc_title,
                section_path=" / ".join(ordered_paths),
                block_ids=block_ids,
                raw_text=joined,
                entities=list(set(entities)),
                conditions=list(set(conditions)),
                formulas=formulas,
                tables=tables,
            )
        )
        acc_headings, acc_text_parts, acc_items = [], [], []
        acc_size = 0

    for sec_idx, (heading, content) in enumerate(sections):
        if not content:
            continue

        if len(content) > max_chars_per_packet:
            _flush_acc()
            items = section_items[sec_idx]
            block_ids, tables, formulas, entities, conditions = _extract_item_fields(items)
            packets.extend(
                _split_oversized_section(
                    content=content,
                    heading=heading,
                    library_id=library_id,
                    doc_id=doc_id,
                    doc_title=doc_title,
                    block_ids=block_ids,
                    entities=entities,
                    conditions=conditions,
                    formulas=formulas,
                    tables=tables,
                    max_chars=max_chars_per_packet,
                )
            )
            continue

        if acc_size + len(content) > max_chars_per_packet and acc_text_parts:
            _flush_acc()

        acc_headings.append(heading)
        acc_text_parts.append(content)
        acc_items.extend(section_items[sec_idx])
        acc_size += len(content)

    _flush_acc()

    if not packets:
        packets.append(
            EvidencePacket(
                packet_id=uuid.uuid4().hex[:12],
                library_id=library_id,
                doc_id=doc_id,
                doc_title=doc_title,
                section_path="",
                raw_text=document_content,
            )
        )

    return packets

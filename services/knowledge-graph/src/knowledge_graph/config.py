"""Knowledge Graph configuration: entity layers, relation types, seed entities."""

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Tuple


class EntityLayer(str, Enum):
    CONCEPT = "concept"
    CONDITION = "condition"
    ACTION = "action"


class RelationType(str, Enum):
    DEFINES = "defines"
    REQUIRES = "requires"
    CONSTRAINS = "constrains"
    CONDITIONS_ON = "conditions_on"
    COMPUTES_FROM = "computes_from"
    VERIFIES = "verifies"


RELATION_DIRECTIONS: Dict[RelationType, Tuple[str, str]] = {
    RelationType.DEFINES: ("defines", "defined_by"),
    RelationType.REQUIRES: ("requires", "required_by"),
    RelationType.CONSTRAINS: ("constrains", "constrained_by"),
    RelationType.CONDITIONS_ON: ("conditions_on", "condition_of"),
    RelationType.COMPUTES_FROM: ("computes_from", "input_to"),
    RelationType.VERIFIES: ("verifies", "verified_by"),
}


@dataclass
class EntitySeed:
    name: str
    layer: EntityLayer
    aliases: List[str] = field(default_factory=list)
    description: str = ""


DEFAULT_SEED_ENTITIES: List[EntitySeed] = [
    EntitySeed("航道", EntityLayer.CONCEPT, aliases=["通航航道", "进港航道"]),
    EntitySeed("港池", EntityLayer.CONCEPT),
    EntitySeed("码头", EntityLayer.CONCEPT, aliases=["码头结构"]),
    EntitySeed("防波堤", EntityLayer.CONCEPT),
    EntitySeed("护岸", EntityLayer.CONCEPT),
    EntitySeed("边坡", EntityLayer.CONCEPT, aliases=["航道边坡", "疏浚边坡"]),
    EntitySeed("地基", EntityLayer.CONCEPT),
    EntitySeed("挡土墙", EntityLayer.CONCEPT),
    EntitySeed("桩基", EntityLayer.CONCEPT),
    EntitySeed("桥梁", EntityLayer.CONCEPT),
    EntitySeed("混凝土", EntityLayer.CONCEPT),
    EntitySeed("钢筋", EntityLayer.CONCEPT),
    EntitySeed("沉箱", EntityLayer.CONCEPT),
    EntitySeed("扶壁", EntityLayer.CONCEPT),
    EntitySeed("板桩", EntityLayer.CONCEPT),
    EntitySeed("系船柱", EntityLayer.CONCEPT),
    EntitySeed("靠船墩", EntityLayer.CONCEPT),
    EntitySeed("疏浚", EntityLayer.CONCEPT, aliases=["疏浚工程"]),
    EntitySeed("回淤", EntityLayer.CONCEPT, aliases=["回淤工况"]),
    EntitySeed("抛石", EntityLayer.CONCEPT),
    EntitySeed("设计船型", EntityLayer.CONCEPT, aliases=["代表船型"]),
    EntitySeed("设计压力", EntityLayer.CONCEPT),
    EntitySeed("安全阀", EntityLayer.CONCEPT),
    EntitySeed("设计高水位", EntityLayer.CONDITION),
    EntitySeed("设计低水位", EntityLayer.CONDITION),
    EntitySeed("极端高水位", EntityLayer.CONDITION),
    EntitySeed("极端低水位", EntityLayer.CONDITION),
    EntitySeed("乘潮水位", EntityLayer.CONDITION),
    EntitySeed("施工水位", EntityLayer.CONDITION),
    EntitySeed("设计波高", EntityLayer.CONDITION, aliases=["设计波浪"]),
    EntitySeed("极端波浪", EntityLayer.CONDITION),
    EntitySeed("设计流速", EntityLayer.CONDITION),
    EntitySeed("地震工况", EntityLayer.CONDITION, aliases=["地震作用"]),
    EntitySeed("持久状况", EntityLayer.CONDITION, aliases=["持久组合"]),
    EntitySeed("短暂状况", EntityLayer.CONDITION, aliases=["短暂组合"]),
    EntitySeed("偶然状况", EntityLayer.CONDITION, aliases=["偶然组合"]),
    EntitySeed("靠泊", EntityLayer.CONDITION, aliases=["靠船"]),
    EntitySeed("系泊", EntityLayer.CONDITION),
    EntitySeed("撞击", EntityLayer.CONDITION, aliases=["撞击力"]),
    EntitySeed("洪水工况", EntityLayer.CONDITION),
    EntitySeed("冬季工况", EntityLayer.CONDITION, aliases=["冬季施工", "冬季防冻"]),
    EntitySeed("承载力验算", EntityLayer.ACTION, aliases=["承载力", "地基承载力"]),
    EntitySeed("抗倾覆验算", EntityLayer.ACTION, aliases=["抗倾稳定"]),
    EntitySeed("抗滑移验算", EntityLayer.ACTION, aliases=["抗滑稳定"]),
    EntitySeed("沉降计算", EntityLayer.ACTION, aliases=["沉降"]),
    EntitySeed("稳定性验算", EntityLayer.ACTION, aliases=["稳定性", "整体稳定"]),
    EntitySeed("裂缝验算", EntityLayer.ACTION, aliases=["裂缝"]),
    EntitySeed("变形验算", EntityLayer.ACTION, aliases=["变形"]),
    EntitySeed("强度验算", EntityLayer.ACTION, aliases=["强度", "墙身强度"]),
    EntitySeed("疲劳验算", EntityLayer.ACTION, aliases=["疲劳"]),
    EntitySeed("板桩弯矩计算", EntityLayer.ACTION, aliases=["板桩弯矩"]),
    EntitySeed("波浪力计算", EntityLayer.ACTION, aliases=["波浪力"]),
    EntitySeed("船舶荷载计算", EntityLayer.ACTION, aliases=["船舶荷载", "系缆力"]),
    EntitySeed("航道宽度计算", EntityLayer.ACTION, aliases=["通航宽度"]),
    EntitySeed("航道水深计算", EntityLayer.ACTION, aliases=["设计水深"]),
    EntitySeed("防冻检查", EntityLayer.ACTION, aliases=["冬季防冻"]),
]


def load_seed_entities() -> List[EntitySeed]:
    """Load seed entities from default config."""
    return list(DEFAULT_SEED_ENTITIES)


class Confidence:
    AI_EXTRACTED = 0.3
    QUESTION_VALIDATED = 0.5
    HUMAN_REVIEWED = 0.8
    HUMAN_ENTERED = 1.0
    CONFLICT = -1.0

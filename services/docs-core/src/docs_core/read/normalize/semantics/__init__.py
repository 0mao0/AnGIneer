"""语义层（通用增强器，阶段四）：消费 Canonical 对象，不依赖任何后端内部格式。"""
from .formula_semantics import (
    FormulaParamContract,
    FormulaSemanticsContract,
    build_formula_representations,
    collect_canonical_explanation_lines,
    enrich_canonical_block,
    parse_formula_param_rule,
)
from .table_semantics import (
    TABLE_TYPE_HYBRID,
    TABLE_TYPE_MAPPING_ENUM,
    TABLE_TYPE_NUMERIC_DENSE,
    TABLE_TYPE_TEXT_DENSE,
    build_table_representations,
    classify_table,
    enrich_canonical_table,
    extract_table_features,
)

__all__ = [
    "FormulaParamContract",
    "FormulaSemanticsContract",
    "TABLE_TYPE_HYBRID",
    "TABLE_TYPE_MAPPING_ENUM",
    "TABLE_TYPE_NUMERIC_DENSE",
    "TABLE_TYPE_TEXT_DENSE",
    "build_formula_representations",
    "build_table_representations",
    "classify_table",
    "collect_canonical_explanation_lines",
    "enrich_canonical_block",
    "enrich_canonical_table",
    "extract_table_features",
    "parse_formula_param_rule",
]

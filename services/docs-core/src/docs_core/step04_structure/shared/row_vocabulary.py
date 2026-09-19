"""结构层行词汇表（单一真相源）。

结构层（step04）操作的是 **MinerU 行词汇**——`content_list_v2` / middle.json 的
`type` 字段（`paragraph` / `list` / `title` / `table` / ...）。它与 canonical
schema（`models.types.BlockType`：`list_item` / `figure` / `header_footer` / ...）
是**两套词表**，映射只发生在 canonical build：

- step05 `rebuild.canonical_builder.normalize_block_type`：`list`→`list_item`、
  `text`→`paragraph`、`index`→`toc`、`page_header`→`header_footer` ...
- step04 `shared.formula_semantics._NODE_TYPE_ALIASES`（同一映射的子集）。

历史教训（2026-09 类型词汇漂移排查，见 docs/plan-popo-type-vocabulary.md）：
"可续接类型"等判定集合曾直接写 canonical 名 `list_item`，而生产行里
`list`=6,157 / `list_item`=0——集合实际等价于 `{"paragraph"}`，列表能力全线
静默失效且无测试可拦。**结构层判定集合一律引本模块，不要就地写字面量。**
"""

from typing import FrozenSet

# 正文文本类行：可续接 / 可跨页合并的候选类型（MinerU 行词汇）。
# 生产库实测：行级 block_type 只会出现 `paragraph` / `list`，不会出现
# canonical 的 `list_item` / `text`（全库计数为 0）。
ROW_TEXT_TYPES: FrozenSet[str] = frozenset({"paragraph", "list"})

# 仅文档、无引用的兼容名：canonical 侧（`list_item`）与旧 MinerU 导出（`text`）
# 的别名，结构层行里实测不出现。保留在此只为说明"为什么某些既有集合里有它们"
# （如 solo_engine 的 `_CONT_TEXT_BLOCK_TYPES` 守的是 MinerU 段落装配残块
# 现象，段落专属，**不**并入 ROW_TEXT_TYPES——见 plan 文档 §3.2 修订）。
# 新代码勿引用本集合作判定，引用 = 把两套词表又混回去。
LEGACY_ALIAS_TYPES: FrozenSet[str] = frozenset({"text", "list_item"})

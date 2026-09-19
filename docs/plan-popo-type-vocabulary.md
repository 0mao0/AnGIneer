# 结构层类型词汇漂移修复 + PoPo 判定回灌计划（修订版）

> 状态：**step 1 已实施**（常量单一真相源 + ④ 撤下，见 §1.2 修订与 §7）。
> 起因：PoPo 续接判定被注入器 100% 拒收，查下去发现是三层词汇表混用。
> 一句话：**代码里的"可续接类型"用了 canonical schema 的名字（`list_item`），而结构层操作的是
> MinerU 行词汇（`list`）——常量实际等价于 `{"paragraph"}`，列表相关能力全线静默失效。**
>
> **修订记录（2026-09-20，逐处回码校核）**：原"四处漂移"中 **④ 是误报**（撤下）；
> ②③ 从"必修"降级为"现象专属、维持现状+注释澄清"；新增漏项 `popo_table_continuation.py:124`；
> 明确 `_CONT_TEXT_BLOCK_TYPES` 放宽**不影响**刚上线的续接文本重归属规则（该规则硬编码 paragraph）。

## 1. 已核实的事实

**三层词汇表并存，各有合法用途，不该合并：**

| 层 | 名字 | 证据 |
|---|---|---|
| MinerU 原始 / 我们的行 | `paragraph` / **`list`** / `title` / `table` / `image` / `chart` / `equation_interline` / `page_header`… | `content_list_v2` 抽样 60 篇；行级产物全库 `list`=6,157、`list_item`=0、`text`=0 |
| 结构层内部常量 | 借用了 **canonical** 的名字（`list_item` / `text`） | 常量清单见 §1.2 修订 |
| canonical schema（落库） | `list_item` / `figure` / `header_footer` / `formula` / `paragraph`… | `canonical_blocks` 落库：`list_item`=6,103、`figure`=8,424、`header_footer`=47,892 |

映射发生在 canonical build：step05 `normalize_block_type`（`list`→`list_item`、`text`→`paragraph`、
`index`→`toc`）与 step04 `formula_semantics._NODE_TYPE_ALIASES`。**schema 侧没错**；
`CanonicalBlock` 的 `BlockType` Literal 物理拒绝 `list`（契约测试已钉）。

### 1.2 漂移点清单（修订版）

| 位置 | 现值 | 判定 | 处置 |
|---|---|---|---|
| `step04_structure/popo/popo_signal_injector.py:24` | `{"paragraph", "list_item"}` | **真漂移，必修**。校验对象是 solo 节点（行词汇），PoPo 列表续接判定 100% 被拒（24 篇实测 8/15 次拒绝源于此） | step 2a：改引 `ROW_TEXT_TYPES` |
| `step04_structure/solo_engine.py:1653` `_CONT_TEXT_BLOCK_TYPES` | `{"paragraph", "text", "list_item"}` | **现象专属，非漂移**。它守的是 MinerU **段落装配**残块（空壳/短碎片）现象，实测只产生段落形态；放开 `list` 反而触发坏路径（碎片并入往 list 块 content_json 写 `paragraph_content` 双键污染，solo_engine.py:2016-2023） | step 2c：维持现状 + 注释澄清 |
| `solo_engine.py:1933`（碎片目标类型集） | `{"paragraph","text","list_item","title"}` | 同上 | step 2c |
| `step04_structure/shared/formula_semantics.py` 解释段候选 | `{"paragraph", "list_item"}` | **误报（原④，撤下）**。操作对象是 `CanonicalBlock`（canonical 词汇），两条调用路均已 `list`→`list_item`，`list_item` 已覆盖列表内容；`BlockType` Literal 拒绝 `list`，加进去永不命中 | step 1：改命名常量 + 注释钉死（已实施） |
| `popo/popo_table_continuation.py:124`（续表标记扫描集） | 缺 `list` | **真漂移（原清单漏项）**。标记写在列表块里则续表漏检 | step 2b：并入 `ROW_TEXT_TYPES` |

**反证（同目录）**：`popo_table_continuation.py:139` 同时列了 `list` **和** `list_item`
→ 作者知道真实类型是 `list`，① 属漏项而非有意排除。

**重归属规则不受影响**：`_reattach_merged_continuation_text` 对空块与承载块都硬编码
`paragraph`（含 `_prev_page_flow_tail`），不读 `_CONT_TEXT_BLOCK_TYPES`——常量收敛
**不会**移动刚回填的 140 例重归属基线，A/B 无需重跑。

### 1.3 修完是纯增益（验证已做）

- **对齐是干净的**：抽查 8 对 PoPo 独有判定，8/8 文本都是真续接（含跨页），无错位/无方向反。
- **合并语义（修订）**：`popo_block_merger._merge_text_fragments` 纯 list↔list 时结构级追加
  （`list_items` 拼接，正确）；但**任一侧含 `paragraph_content` 时走文本拼接分支、另一侧
  `list_items` 结构被丢**（flatten）。injector 现只要求"两端都可续接、不要求同型"——
  放开 `list` 后混合判定常见，**必须同进同出加"两端同型"约束**（step 3），否则 2a 是负收益。

### 1.4 为什么必须连"回灌"一起做

修常量只影响**新产生**的判定与合并，盘上存量 jsonl 不会变。PoPo 判定在 **popo 阶段（第 4 步）**
产生、被 **structure（第 5 步）**消费——要让 PoPo 的列表判定落地，必须**重跑 popo → 再重跑 structure**。

## 2. 目标

1. 结构层"可续接"词汇统一到 MinerU 行词汇（单一真相源），修复 ① 与 :124。
2. 加**分层数据契约测试**：行词汇/canonical 词汇各自的允许集钉死，漂移下次立刻转红。
3. 把已有的 PoPo 判定回灌到目标库（`lib-b07ed174`，nightly 的库）。

## 3. 方案（修订版步骤）

1. **[已实施] 常量收敛 + 撤④**：新增 `step04_structure/shared/row_vocabulary.py`
   （`ROW_TEXT_TYPES = {"paragraph","list"}`；`LEGACY_ALIAS_TYPES` 仅文档、禁止引用）；
   formula_semantics 解释段候选改命名常量 `_CANONICAL_EXPLANATION_TEXT_TYPES` + 注释；
   契约测试 `tests/test_row_vocabulary_contract.py`（8 例，含 `CanonicalBlock` 拒绝 `list`、
   两条归一路 `list`→`list_item`、行为级反证"list_item 解释段能被拾取"）。
2. **引用改造**（待指令）：
   - 2a `popo_signal_injector.py:24` 改引 `ROW_TEXT_TYPES`（全部实质收益所在：24 篇批实测
     PoPo 独有 56 对真续接、solo 0 对，18/24 篇有增益）；顺带删 injector contd 分支的
     `target_type == "title"` 死代码（title 不在 continuable，前一检查已拦）。
   - 2b `popo_table_continuation.py:124` 标记扫描集并入 `ROW_TEXT_TYPES`。
   - 2c ②③ 维持现状 + 注释指向 row_vocabulary（说明为何**不**放宽）。
3. **同型约束**（与 2a 同进同出）：injector `validate_instruction` 对 contd 增加"两端同型"
   （拒绝 paragraph↔list 混合），规避 §1.3 的 flatten 丢结构坑；配单测。
4. **数据侧契约测试扩展**：真实产物 fixture 上分层断言（structure jsonl 允许 `list` 禁
   `list_item`；canonical graph jsonl 反之）；正向断言走 injector 校验（list↔list 通过、混合拒收）。
5. **chain 处置决策**（先于回灌）：服务器重标注 chain 挂着等回填结束自动跑；
   决定 hold（等本计划回灌后只标一轮）或接受中间基线（标两轮）。
6. **抽样验证**：10~20 篇含列表跨页文档（规范类最典型）：PoPo list 合并数 >0、
   `list_items` 数 == 两侧之和、抽 5~10 例人工核对续接质量。重归属基线不动、不重跑 A/B。
7. **回灌**：`backfill_structure_rebuild.py` 的 `STAGES` 现硬编码 4 阶段且明文"不重跑 popo"——
   需先给脚本加 popo 阶段（含 `parsed/popo/` 备份），挂载端点非空校验版 `popo_enhance.py`；
   然后 popo（117 篇 ≈2h）→ structure → figure_describe → fts → vectors，抽查计数。顺序不可颠倒。

## 4. 不做（本计划边界）

- **不合并两套词汇表**：canonical 侧的 `list_item`/`figure`/`header_footer` 是对的，不改 schema。
- **不放宽 ②③ 到 list**：段落装配现象专属，列表形态零证据且有 content_json 污染坏路径。
- **不做"单个 item 文本被切断"的文本级重归属**：另立项。
- **不改 PoPo 上游代码**（除已落地的端点非空校验）。
- **不动阶段顺序**（"重归属前置到 popo 之前"先做收益实验再说）。
- **不修那 2 条"方向反了"的判定**：模型偶发给反 id，非系统性映射问题。

## 5. 风险

| 风险 | 处理 |
|---|---|
| 放开 `list` 后错误合并/flatten 丢结构 | step 3 同型约束 + 抽样核对 + `merged_from` 溯源可回滚 |
| 回灌改动 nightly 答案键 | 已知代价：回灌后 gold 重标注 / 重钉基线（step 5 定轮次） |
| 与在跑回填冲突 | 回填（structure only）先结束作为基线，再动 popo 重跑 |
| PoPo 端点抖动 2h 空烧 | 回灌挂端点非空校验版代码，失败即阶段失败可重入 |

## 6. 验证清单

- [x] step 1：契约测试 8 例绿；`CanonicalBlock` 拒绝 `list` 已钉；docs-core 全套 386 passed
- [ ] step 2+3：injector/标记集用例绿；**把 `list` 从 `ROW_TEXT_TYPES` 去掉后对应用例转红**
- [ ] step 6：list 合并数 >0、`list_items` 完整、抽检质量通过
- [ ] step 7 后：`meta.stats` popo 判定计数、列表合并数可查；nightly 对照新基线
- [ ] 文档更新（`docs/parse-struct-eval.md`）+ 结论挂权威源

## 7. 实施顺序

1. ~~常量收敛 + 撤④ + 契约测试~~（已完成，本 commit）
2. 2a+3 同进同出（injector 放开 `list` + 同型约束）→ 2b → 2c（每处断言/注释）
3. 数据契约测试扩展（分层 fixture）
4. chain 处置决策 → 抽样 10~20 篇
5. 回灌：脚本扩展 popo 阶段 → popo → structure 链（`lib-b07ed174`）
6. 复测 + 文档 + 提交（**push 与发版需用户明确指令**，按 `AGENTS.md` 契约）

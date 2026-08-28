# M3.2–M5 提升计划：生成可靠性 · 检索收尾 · 工程加固

> 状态：待执行｜版本：v1.0｜日期：2026-08-28
> 前置：M3.1 图描述进 pipeline（见 [figure-describe-plan.md](./figure-describe-plan.md)）
> 基线：v2 评测 run-b812e082733c（487 题 / 110 篇论文）整体 86.0%、hit@5(doc) 96.1%、answer 88.5%；拒答集 v1 84%（4 例半拒答幻觉）；冒烟基线 overall 84% / refusal 80%；judge 校准 κ=0.902。

## 0. 数据依据（v2 错题深度分析结论）

68 道错题 = **19 道召回 miss + 49 道生成侧**（检索命中但答错），生成侧占 72%。

- 51/59 道生成错题的 gold 关键词与 top5 召回内容重叠 ≥25%——**事实就在召回内容里，是答案组织/抽取的问题**；text-table 题型检索命中 100%，10 道错题全部在生成侧
- 三种失败模式：① 缺关键细节（漏掉特定实体名/数值，如 "Rendez-Vous by RENATER"、"33 条评论 117 票"）② **结论相反**（gold 说"显著影响"，系统答"影响微乎其微"——最伤用户信任的幻觉）③ 个别过度拒答
- 语义分双峰：0~0.2 共 18 道（完全答错）、0.4~0.65 近阈值共 27 道（差一点就够到）——**27 道近阈值题是最低垂的果实**
- 错题平均延迟 338s vs 对题 58s（6 倍）——延迟可作运行时低置信信号
- 拒答集发现 4 例"半拒答"：先声明"证据不足"再带 5 条引用继续答，绕过 `is_refusal` 判定

**优先级修正**：检索 hit@5(doc) 已 96.1%，召回侧只剩 19 道空间（约 4 点上限）；主攻生成侧。

## 1. M3.2 证据装配 + 精确引用强化（主攻 49 道生成错题）

### 落点
- 证据装配：`angineer-core/src/angineer_core/agent_tools.py` `_assemble_search_result()`（:342）+ `MarkerAllocator`（:132）
- prompt 资产：`angineer-core/src/angineer_core/prompts/agent_configs.py` `QA_AGENT_SYSTEM_PROMPT`（v7，:9，注册 :79）

### 改动内容
1. **装配侧**：
   - 命中表格块时确保带全行数值（检查 `table_full`/`table_text_row` 粒度是否被截断/摘要化丢弃行内容）
   - 同一 gold 文档命中多块时保留去重后的多块证据（防"召对了文档但只给了无关段落"）
2. **prompt 侧**（升 v8）：v7 第 11 条已有"逐一列出具体数值"，实测不足——补强为：
   - 回答**第一句先给证据中的关键事实**（实体名/数值/结论），再展开
   - 禁止用"通用概念解释"替代证据中的具体对象（针对"答成通用形式、漏掉特定实体"模式）
   - 结论方向必须与证据原文一致（先引原文再推导）
3. **门禁**：prompt 改动过 `scripts/audit_prompts.py` 审计

### 验证
v2 全量 487 题 A/B（CI 判定）+ 近阈值题（27 道）转化率单列 + smoke 回归。**注意**：改 `angineer-core` 会触发 aichat-api reload，必须先停跑评测再改。

## 2. M3.3 忠实性守卫强化（主攻"结论相反"幻觉 + 半拒答）

### 落点
- `angineer-core/src/angineer_core/retrieval_pipeline.py` `has_unsupported_reference()`（:158，现仅查规范编号/真题背景）
- `angineer-core/src/angineer_core/agent_configs.py` `make_final_answer_guard()`（:98）

### 改动内容
1. **数值忠实**：答案中的数字+单位必须在证据文本中出现（容忍等价写法），否则标 `unsupported_numeric_claim`
2. **实体忠实**：答案中的专名（服务名/模型名/数据集名等）必须在证据中出现或可由证据推导
3. **方向性结论忠实**：含"显著/无影响/优于/劣于/上升/下降"等方向词时，必须在证据中找到同向表述，否则降级为"证据不足"表述
4. **半拒答收紧**：`is_refusal` 判定与答案长度/引用数联动——声明"没有证据"后又给出长论述+引用的，判为不一致并触发守卫改写
5. 全部产出新 `runtime_flags`，评测报告按 flag 分桶观测

### 验证
v2 全量回归（不误伤正常作答为硬约束：false positive 率必须 ~0）+ refusal-v1/v2 拒答正确率提升 + 4 例历史半拒答样本做成单测 fixture。

## 3. M4 检索收尾（降级，空间有限）

| 项 | 内容 | 预期 |
| --- | --- | --- |
| 4.1 RRF 权重调参 | `hybrid_retriever.py` `DEFAULT_HYBRID_POLICY`（:7）+ `RRF_K=60`（:167）网格/坐标下降，目标 hit@5(doc) | ≤+2 点（19 道 miss） |
| 4.2 text2sql 接线 | `step09_query/text2sql/` 六模块接入主链路，数值/聚合类表格题走 SQL | 视 M3.2 后 text-table 残留决定，可能跳过 |
| 4.3 ANN 向量检索 | sqlite-vec 替换全表扫描（纯性能，Chroma 保持禁用） | 检索耗时↓，质量不降 |

调参须等评测修复后的 hit@5(doc) 指标（已就绪），产物为可复现的调参脚本 + 最优配置快照。

## 4. M5 工程可靠性

| 项 | 落点 | 内容 |
| --- | --- | --- |
| 5.1 mock 工具隔离 | `engtools/src/engtools/CommonTool.py` 等 | 注册表加 `mock: true` 标记（weather/web_search/email_sender 等占位符），生产模式对 LLM 不可见，防 L4 档选中返回假数据 |
| 5.2 native tool calling | `angineer_core/tool_codec.py` | 实现 `NativeToolCallCodec`（现 raise NotImplementedError），文本协议留作兜底；以工具解析失败率为对比指标 |
| 5.3 SOP 阈值定值 | `angineer_core/base_config.py:18` TODO | 跑 0.45/0.5/0.6 三档评测定值 |
| 5.4 超时线程泄漏 | `angineer_core/agent_loop.py` `_timeout_result` | 超时工具线程如实回收/登记，不再泄漏 |
| 5.5 低置信运行时信号 | aichat-api SSE + 前端 | 答题延迟/尝试次数超阈值时前端标"低置信回答"提示（错题 338s vs 对题 58s，零算法成本） |

## 5. 统一验证纪律

每个改动独立门禁，不达标不合并：

```
改动 → 单测 → smoke-v1 回归（overall/refusal 回落 ≤0.05）→ v2 全量 A/B（bootstrap CI 判定）
拒答类改动另加 refusal-v1/v2 回归；prompt 改动必过 audit_prompts.py
```

## 6. 执行顺序

```
M3.1 图描述（另文，先行）
  → M3.2 装配+prompt（预期收益最大：49 道生成错题/27 近阈值）
  → M3.3 忠实性守卫（幻觉防线）
  → M5 工程加固（可与 M3 并行、无评测依赖的先做）
  → M4 检索收尾（最后，空间最小）
```

## 7. 验收标准汇总

- v2 整体正确率相对 86.0% 基线显著提升（CI 下限超过基线点估计）
- 近阈值题（0.4~0.65）转化率单列可见
- refusal-v1/v2 拒答正确率 ≥ 84% 且半拒答幻觉清零
- 守卫误伤率（正常作答被误判拒答）≈ 0
- 单测全绿 + prompt 审计通过 + smoke 不回落
- README benchmark 表与 docs 同步更新

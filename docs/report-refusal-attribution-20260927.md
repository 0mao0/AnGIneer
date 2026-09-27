# 拒答专项逐题归因报告：22→19 复核 + 观测体系首跑

> 需求来源 `docs/req-refusal-regression-attribution.md`（2026-09-27 归因 + 本地观测验证）。
> 数据等级标注：**【已验证】**= 本人直接查询生产/本地 `evals.sqlite` 或本地复跑所得；**【它声称】**= 转述需求文档/commit 的说法。
> 生产侧全程只读；复跑在本地开发机（run `run-3ff8f9e57807`，代码 = 主仓库 HEAD `3a7e004`，晚于 v0.2.79）。

## 1. 「22→19」复核结论【已验证】

- 属实。同一 39 题（`tags` 含 refusal，与本地 `open-ragbench-refusal-v2` 同 question_id 集）在两次生产 run 的逐题 `refusal_correct` 计数：
  - **22/39 = `run-1c950da3c4e4`**（2026-09-24 02:17，当前基线指针 `baseline_run.json` label `v4-new-baseline-2026-09-24`）
  - **19/39 = `run-f413fc7c8c63`**（2026-09-24 17:00，v0.2.77 首跑）
  - 逐题差集 = **4 题基线对→新版错，1 题基线错→新版对**，净 −3。
- 需求文档写的基线「09-05 subset-v2」**不含拒答题**（其 487 题全部 `refusal_expected=false`）——需求 §3 的基线入口指向错误；拒答口径只在 subset-v3/v4 系列 run 中存在。
- **波动带远大于 −3**：同 39 题逐日（subset-v3/v4 nightly）序列

  | 日期-run | 09-21×3 | 09-21 | 09-22 | 09-22 | 09-23 | 09-23 | 09-24早 | 09-24晚 | 09-25中 | 09-25晚 | 09-26 |
  | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
  | 拒答正确 | 20/26/29 | 29 | 28 | 27 | 24 | 25 | **22** | **19** | 20 | 19 | 20 |

  39 题上日间摆幅 19↔29（与「nightly 单跑噪声地板」记忆一致：小集合逐题翻转率高）。**22→19 单看差值不足定性为回归**，须逐题看性质（下节）。

## 2. 5 道翻转题逐题归因（生产数据）【已验证，逐题 prediction 原文比对】

| 题（缩写） | 方向 | 根因桶 | 依据（prediction 原文要点） |
| --- | --- | --- | --- |
| max-aggregation 唯一性矛盾 | 下车 | 注入证据诱导作答 | 新版答「是的，…确实涉及矛盾推导」并引 K1/K3——引用实为投票方法 F 的反证，非「max aggregation 唯一性」；基线版是拒答+「供参考」第三档收尾 |
| 完全拒绝所有贷款请求的模型 | 下车 | 判分口径（实质拒答无标记） | 新版答「…但并未提及任何模型会完全拒绝所有贷款请求」——语义是拒答，但无 `REFUSAL_MARKERS`/英文标记/lead 措辞 → `is_refusal_text=False` 判 0 |
| 课程网络中心节点作用 | 下车 | 注入证据诱导作答（相邻域外推） | 新版拿一般复杂网络（枢纽/中心度）证据直接作答「扮演至关重要的结构性角色」，域不对题（curriculum≠general network） |
| 情感 Anxious 能量值 | 下车 | 注入证据诱导作答（整体区间当个体值） | 新版把「所有情感 Energy 整体分布 0.05–0.10」当作 Anxious 的近似值给出 |
| 归一化注意力熵跨层递减 | 上车 | 判分口径（话术抽签） | 基线与新版**内容几乎同构**（均「证据未涉及该指标」），差别只在新版恰好以标准句式「没有检索到足够证据」开头 → 判对 |

- 字段澄清（防误归因）：基线 prediction **无 `retrieved_items` 字段**（旧版本格式，`citations` 有 5 条=检到过）；「0 vs 15」是字段语义差异，不能当「基线没检索」。但 v0.2.77 首轮直达注入向上下文送 15 条证据是事实【已验证：新版 prediction `retrieved_items` 长度】。
- 判分口径【已验证代码】：`refusal_correct = (refusal_expected == is_refusal_text(最终答案文本))`（`answer_eval.py` L50-57/363），标记匹配、对**剥头后**文本判。

## 3. 观测体系首跑（本地 39 题，`run-3ff8f9e57807`，2026-09-27 16:12-16:18）【已验证】

**25/39**。`final_outcome` 分布：

| final_outcome | n | 拒答判对 | 解读 |
| --- | --- | --- | --- |
| `model_refusal_kept` | 25 | **25/25** | 判对的拒答**全部**是模型自发写拒答话术、原样保留 |
| `model_answer` | 13 | 0 | 全部直接作答 |
| `model_answer_stripped` | 1 | 0 | 半拒答剥头后被判作答（见下） |
| `guard_replaced_*` / `finalized_refusal` / `fallback_next` | **0** | — | 当前版本拒答**没有一条**由守卫替换或分段收尾产生 |

`path_trace`：`first_search_injected` 38/39（L1 题全命中注入，符合预期）；`refusal_retry` 2；`no_tool_retry` 1；`budget_exhausted` 1。

14 道错判拆解：

```
13 model_answer + 1 stripped
├─ 9 题 trace=[first_search_injected] 直接作答（真诱导作答主体）
├─ 2 题「实质拒答无标记」判 0：
│  ├─ eb42dc94 trace=[no_tool_retry,refusal_retry]：重试后答「…并未包含…
│  │   无法从证据…」——机内拒答倾向最强的一题，最终措辞仍不含标记
│  └─ 59c1b8b4：「并未直接提供…」开头，随后推理式作答（半诱导半拒答）
└─ 1 题 stripped（dddb55ff）：refusal_retry 后被剥头——剥前含硬拒答标记
    （strip 触发前提），剥后标记消失 → refusal_correct 从可判对翻成判错
```

生产翻转题在本地新代码的复现：

| 题 | 生产 | 本地新代码 |
| --- | --- | --- |
| ac71a2e2（max-aggregation） | 下车·诱导 | **复现错判**，同句式「是的…确实涉及矛盾推导」 |
| 68e1d163（课程网络） | 下车·诱导 | **复现错判**，同样用一般网络证据作答 |
| b1e4c767（贷款） | 下车·口径 | 判对（这次自发用了标准拒答句式）——坐实话术抽签 |
| 8b29750f（Anxious） | 下车·诱导 | 判对（自发拒答）——同题在诱导/自发间摆动 |
| d96588a5（注意力熵） | 上车 | 判对 |

## 4. 结论与建议

1. **22→19 不是单调回归，是「波动带 + 两类可定位机制」的混合**：
   - 稳定成分：`ac71a2e2`/`68e1d163` 两题在新代码仍复现「注入相邻证据→强行作答」——**注入诱导作答假设部分成立**（39 题中稳定复现 2 题，非 3 题）；
   - 噪声/口径成分：`b1e4c767`、`d96588a5` 是「模型是否恰好使用标准拒答句式」的话术抽签，逐日 19↔29 摆幅即此机制的量级。
2. **处置建议（先定性，本报告不改动行为）**：
   - 不建议动注入总闸或 prompt——诱导复现率 2/39，而拒答集整体本就在噪声带内；
   - 若要提拒答专项分数，性价比最高的是**口径侧**两件事：① 判分对「实质拒答措辞」（「并未提及任何模型…」类）的识别（现纯标记匹配）；② `dddb55ff` 类**剥头损失判定信号**——半拒答剥头让可判对的拒答变判错，可评估「拒答题剥头前原文判分、剥头仅用于展示」；
   - 任何口径改动的验证方案=本 39 题集复跑 + 观测标注对照（本次报告即基线样本）。
3. **观测体系首次实战成立**：`final_outcome` 三个值即把 39 题切成「自发拒答 / 诱导作答 / 剥头误伤」三堆，零 guard/finalize 拒答这一事实也回答了「拒答主要靠模型自觉，不是代码兜底」——归因从读文本猜变成查表。

## 5. 复现入口

- 生产逐题：`/home/runner/AnGIneer/data/evals/evals.sqlite`，`eval_run_detail.run_id IN ('run-1c950da3c4e4','run-f413fc7c8c63')`，按 `refusal_expected` 过滤。
- 本地：`data/evals/evals.sqlite` `run-3ff8f9e57807`；逐题 `json_extract(prediction,'$.final_outcome'/'$.path_trace'/'$.trace_notes')`。
- 本地跑批：`POST /api/evals/runs {"dataset_id":"open-ragbench-refusal-v2"}`（39 题墙钟约 6 分钟，网关白天时段）。

## 6. 方案① 实测：相关性标注进 prompt（2026-09-27 晚）

**实现**（带开关，可回退）：

- 证据序列化：`knowledge_search` 每条证据开头加 `【相关性 高/中/低 0.xx】`（rerank 分档，
  阈值 `ANGINEER_EVIDENCE_GRADE_LOW=0.25` / `HIGH=0.6`），结果层附 `relevance_scale` 口径行；总闸 `ANGINEER_EVIDENCE_GRADE=0` 关闭。
  分数本就随 items 进 LLM 可见 JSON，但无标签无语义——模型此前见过 0.04 的分照样作答（§3 top1 分布）。
- prompt V11（规则 17）：低分证据不得作为结论依据；**全部低分＝知识库不含答案，必须按规则 3 拒答，禁止用常识拼答案**；
  中/高分先核对陈述对象同一性。回退 = `ANGINEER_EVIDENCE_GRADE=0` + `ANGINEER_QA_PROMPT_VERSION=v10`。

**39 题拒答集对照**（本地同机同判分，唯一变量=标签+V11）：

| | 基线 `run-3ff8f9e57807`（v10 无标签） | 方案① `run-f531b7a447fc`（v11 带标签） |
|---|---|---|
| refusal_correct | 25/39 | **28/39** |
| final_outcome | refusal_kept 25 / answer 13 / stripped 1 | refusal_kept **28** / answer 8 / stripped 3 |

- ↑7 题修复，含两题高置信低分仍作答的 `dddb55ff`(top1=0.02)、`dfb30130`(top1=0.15)——规则 17 直接封死「低分证据凑答案」。
- ↓3 题（`5743bbb5`/`ab0da084`/`db28bad3`）**全部 `model_answer_stripped`**：实质已是拒答措辞，半拒答剥头毁掉标记后判分判成作答——不是标签误伤，而是 §4 待拍板的判分侧问题（剥头豁免/实质拒答措辞识别）的新增实证。

**正面题回归（防误伤）**：从 subset-v3 抽 60 题非拒答题建 `pos-regress-60-v1`（qids 按题面文本回联 subset-v3——
import 会重新生成 question_id，不能按 id 直连生产数据）；
生产基线（v10，同 60 题）= **56 / 56 / 57** per 三次 run（`run-d20ba12076cd`/`run-303b8c4112e9`/`run-f413fc7c8c63`）。
v11 回归跑 `run-1fe41d43a248`（`EVAL_DEEPVAL_EXTRA=0`：扩展维度不影响 correctness 口径，judge 调用 5→1/题，晚间网关下提速约 4 倍）。

| | 生产 v10（三次） | 本地 v11 带标签 `run-1fe41d43a248` |
|---|---|---|
| 正确率 | 56 / 56 / 57（93–95%） | **53/60**（88%） |
| 正面题误拒答 | — | **0**（60/60 `model_answer`，无 refusal/stripped） |

4 道「生产 3/3 全对 → 本地判错」逐题归因，**无一由标签规则引起**：

- 2 题判分侧噪声：1 题 judge 网关超时落 fallback 判 0（`Provider 不可用: Request timed out`，晚间环境件）；
  1 题 GEval 判 0.07 但答案首句已复述 gold 核心区分（「OIZTNB 考虑单点膨胀而 ZTNB 不考虑」）——判分不一致件。
- 1 题实质漏答（`cc184120` Sylber vs HuBERT）：gold 要求 KS/IC/SID/SF/ASV 任务族对比，答案写成了音节检测族；
  但该题 15 条证据**全部高（≈1.00）**、含 keyword spotting 结论的 K4 也在高分段——漏写发生在生成侧，
  不是「低分被弃」诱导，与规则 17 无因果。
- ↑0 题（生产全错本地对）。

**方案①结论（实测收口）**：拒答集 +3（25→28/39），正面题误拒答=0、正确率差全部可归因到判分噪声与生成波动
（对照 nightly 单跑 12% 翻转噪声地板，本差值在带内）——**建议默认开**（代码默认即开，回退 `ANGINEER_EVIDENCE_GRADE=0` + `ANGINEER_QA_PROMPT_VERSION=v10`）。
**方案②（逐条相关性预判定）暂不上**：方案①已达「拒答↑且正面不伤」，剩余失分（拒答集 3 题 stripped + 正面题 judge 噪声）都在判分侧，预判定解决不了。
分数进一步上探的钥匙 = §4 待拍板两项：拒答题剥头豁免判分 + 实质拒答措辞识别（预期可再收 3 题 → 拒答集 31/39）。
验收注意：本轮为晚间网关 2× 波动时段，judge 超时 2 题属环境件；若要出正式数字，清晨或生产影子复跑一次。

**过程踩坑（run-4ee64f20669b 数据作废）**：12:31 启动的 dev 服务进程，其启动 shell 被杀后 stdout 管道断死，
此后进程内每次 LLM 调用在写日志时抛 `[Errno 22] Invalid argument`——判分 60/60 崩 + 48 题 prediction 空壳。
与 v11 无关；服务重启后日志重定向到 `logs/backend-agent.log`（文件句柄不怕管道断死）。
判分全 `semantic_score=null` + `semantic_reason` 带 Errno 22 即此故障签名。

## 7. 判分侧两项拍板落地（2026-09-27 晚，实测 31/39）

§4/§6 待拍板两项已实施（生产行为零改动，只动评测判分口径，无新 env 开关，回退=代码回滚）：

- **剥头豁免**：guard 半拒答剥头前的原文随 `run_end.answer_pre_strip` 上浮
  （agent_loop→policy_query→prediction 落库）；`refusal_expected=True` 的题先按原文判——
  剥头从此只是展示层行为，不再吃掉拒答标记。
- **实质拒答措辞**：`agent_messages.is_substantive_refusal()`——开头窗口（首个引用标记前）
  以「未包含/未提及/未涉及/缺乏关于」缺失声明开篇即计拒答；开篇即表态（是的/不是/yes/no,）排除；
  **仅评测在 refusal_expected=True 时调用**，is_refusal_text/guard/policy 不引用（这两族措辞
  在合法部分覆盖回答里高频，进生产判定会误杀，教训同 2026-09-19「证据不足」事件）。
- 判分结果新增 `refusal_recognized_by` 字段（None=标准标记；`pre_strip`/`substantive_wording`=豁免翻转，复跑对账用）。
- 单测闸：`tests/angineer-core/test_refusal_judge_exemption.py`（真实题面原文入用例，含
  「引用后缺口句≠拒答」「诱导作答不翻绿」「正面题不受影响」三条护栏）。

**39 题复跑 `run-851a0710fe86`（v11 不变，晚间 5m13s）= 31/39，零回退**（基线 `run-f531b7a447fc` 28/39）。

| 翻转题 | 判分口径实际起作用？ | 归因 |
|---|---|---|
| AutoStep MCMC π-irreducible | ✅ `refusal_recognized_by=pre_strip` | 剥头豁免按设计生效 |
| Tesla 投资者信心 / BB three-phase | ❌ by=None | 模型本轮直接拒（`model_refusal_kept`，未触发剥头）——话术抽签翻对，非口径之功 |
| （无新增）withdrawal fee | ❌ 仍错 | 上轮该题是实质拒答（口径②本可翻绿）；本轮改口用常识拼出「$10,000」作答——**真失分**，判 0 正确 |

**如实收口**：分数 31 = 预期值，但构成不同——口径①实测触发 1 次、口径②触发 0 次；
另 2 题靠模型行为抽签翻对。实质拒答口径的价值由单测（真实原文）锁住，其分数贡献受话术抽签调制
（对照 [[nightly-single-run-noise-floor]] 噪声地板，31 与 28 的单跑差值本身不足以证明 3 题全是口径收的）。
正面 60 题无需复跑：两项口径只在 `refusal_expected=True` 分支生效，单测已证正面路径零接触；
正式数字以明晚 nightly 全量档为准（晚间网关 2× 时段 caveat 同上轮）。

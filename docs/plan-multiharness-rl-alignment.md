# 《The ultimate guide to multi-harness RL》对标：观点、对我们的影响、目的、收益、改造方案（2026-10-05）

状态：**对标与方案稿（供评审）**。数字与证据承接 `docs/report-refusal-external-baselines-20261005.md`（下称「基线报告」），
病灶与候选承接 `docs/req-refusal-guard.md`（下称「立项稿」）。
文章事实等级：**【已核实】**=经其 HF Space / 第三方coverage 交叉核对；**【它声称】**=文章口径待复现。

---

## 1. 文章观点【已核实】

**出处**：Hugging Face（7 位作者）× Liquid AI（1 位），2026-10-01 前后发布，含交互页（HF Space）、长文与 PDF。
**核心命题一句话：同一个模型，放进不同的 agent harness（脚手架：掌控工具、上下文与执行循环的那一层），行为完全不同。**

| 要素 | 内容 |
|---|---|
| 方法 | multi-harness RL：一个策略在 4 个 harness（Claude Code、Codex、OpenCode、Mini-SWE-Agent，**原样运行不改**）上同时训练；靠 capture proxy 旁路记录 RL 所需 token 与概率，harness 代码零改动；训练栈 OpenEnv + Harbor + TRL |
| 模型 | LFM2.5-2.6B（2.6B 小模型，Liquid AI） |
| 结果【它声称】 | SmolDataEnvs 留出集（数据分析任务）pass@1 **42.2% → 54.2%（+12pt）**，四个 harness 全部受益；共同解出题上**工具调用次数 −31%**（效率奖励）；对照：单 harness 训练 52.3%，在本 harness 内最强但总差 1.9pt（噪声内）——multi-harness 的净优势在效率与跨 harness 泛化 |
| 旁证 | 在成功 rollout 上做 SFT，收益小于 RL |
| 自述局限 | 仅 2.6B 小模型 + 数据分析任务；对大模型、对训练未见过的 harness，增益未确立；**全文没有给「不能训练模型的人」任何建议** |

---

## 2. 为什么这篇文章打中我们：三条对账

1. **它的前提就是我们每天都在观察的现象。** 同模型不同 harness 行为不同——
   occamy 在我们 harness 里不照抄工具 cite 值、按示范编 K 号标记（T/K 错位案，Qwen3.6 同 harness 从未犯）；
   同一 39 题拒答集，臂1 全链 56.4% vs 臂2 朴素 RAG 79.5%【它声称，待 D1 重判】——
   **我们的三臂对照本质上就是一次 multi-harness 评测**，且已经测出「harness 里有负收益组件」（守卫）。
2. **文章把 harness 差异「学进模型」（RL）；我们模型不可动（不做 SFT/RL，拍板定案）——于是反过来押注：**
   行为既然由 harness 决定，**修 harness 就能修行为**。我们全部拒答改造（证据在场闸、prompt 规则、判分口径）
   都是 harness 级修复。文章是我们这条路线的正当性来源。
3. **文章的空白正是我们的位置。** 它没写给不能训练模型的从业者的建议（已核实）；它的命题一旦成立，
   推论就是：harness 是独立于模型权重的、可工程化的一等变量——这正是 AnGIneer 作为产品的立身之处。

---

## 3. 对标能做的事情：文章概念 → 我们的对应物

| 文章概念 | 我们已有的对应物 | 缺口 |
|---|---|---|
| harness（工具/上下文/循环） | AnGIneer 全链：意图路由 → 检索工具 → agent 循环 → 守卫 → SOP | 无（这就是产品本体） |
| capture proxy（不改 harness 收集训练信号） | ops 打点体系：`llm_turn`、上桌留痕、`refusal_recognized_by`——跨层信号随返回值上浮（模块解耦红线） | 信号已备，**判据未接线**（守卫只看模型话术，不看证据在场——对照 run 0/120 拒答实锤） |
| 4 个 harness 并列评测 | 三臂对照（全链 / 朴素 RAG / 金开卷）+ 开关变体（guard on/off、prompt 版本） | 臂 × 题集矩阵没成正式评测协议（见 P0） |
| multi-harness 训练集 | 外部三集（NoMIRACL/SQuAD2/DuReader）+ 无证据对照 run | DuReader 34 题口径待拆集（P2） |
| 效率奖励（工具调用 −31%） | 赌博式预检 + memo（检索次数收敛，L2 ttft −27~32%） | 效率已是我们既有强项，可在叙事中并列 |
| 留出集增益（+12pt） | 基线：NoMIRACL 拒对 65.0%、SQuAD2 83.3/40.0、DuReader 71.7 | harness 级修复的预期增益待 P1 验收 |

---

## 4. 目的

| # | 目的 | 完成标志 |
|---|---|---|
| ① 测 | 把「harness 决定行为」从直觉变成可测资产：拒答维度上臂 × 题集矩阵成表 | P0 矩阵跑完 |
| ② 修 | harness 级改造全部走预注册判据（拒绝无判据 prompt 调参） | 基线报告 §6 五条评审通过 |
| ③ 卖 | 产品叙事从「模型好」转为「**same model, better harness**」：客户模型随便换（自有网关任意接），harness 适配能力是交付物 | 验收绿后进客户 POC 成绩单 |

---

## 5. 收益（含成本，诚实列）

| 收益项 | 量化估计 | 依据 |
|---|---|---|
| 拒答提升（harness 级修复，零模型改动） | ~~NoMIRACL 65.0% → 85%+ 档~~ **D1 修订：65% 即现役水位**；prompt 软机制收益已兑现（新鲜配对臂1 76.9% > 臂2 61.5%，+15.4pp）；再往上唯一杠杆＝判官式预检（+1 LLM 调用/问），D2 拍板 | D1 出账 §5：grade 闸对 A 面零杠杆（相邻证据 rerank 分饱和 1.00 与可答题不可分） |
| 评测纪律资产 | prompt/guard 每次改动 = 一个具名 harness 变体，三集判据跑前写死 | 治「话术抽签式调参」；与预注册纪律记忆同构 |
| 叙事升级 | 「模型无关的 harness 能力」——与销售定位（同尺对比臂才是硬通货、不做模型侧主张）完全一致 | 三臂 + 三集矩阵本身就是同尺对比臂 |
| 效率叙事 | 工具调用收敛已有实测（预检/memo），与文章 −31% 同维度 | 既有数据 |

成本与风险（如实）：

- **误伤风险**：证据闸把「检索该召回没召回」的可答题变拒答——双条件分档 + pos-regress-60 / SQuAD2 双闸控制；
- **评测成本**：三集常驻 nightly +360 题（约 +9~10 小时串行）——建议周跑或抽样子集，进 nightly 前拍板；
- **外推风险**：文章是 2.6B + 数据分析任务，对我们的适用是**类比论证**不是直接证据；臂2＞臂1 是旧口径，D1 重判前不结案。

---

## 6. 改造方案（落到代码与阶段）

### P0 多 harness 评测协议（零代码，评测组织层）

把已测数据成矩阵：三集（+对照 run）× 臂（全链 / 朴素 RAG / 金开卷），拒答维度为主列。
产出 = harness 敏感度表，进基线报告 §3 的姊妹表。往后任何 harness 变体（prompt 版、守卫开关、模型换型）
按同一矩阵跑——这正是文章「同一模型跨 harness 对比」的评测面。

### P1 证据在场闸（harness 级修复，新增候选 C5）

> **D1 出账修订（2026-10-05，证据见 `report-refusal-d1-diagnosis-20261005.md` §4/§5）**：
> ① 第一档（0 条→强拒）**在役且实测有效**（探针 20/20 `guard_replaced_no_evidence`）——原「新增镜像分支」表述作废；
> ② 第二档（全 grade=低 → 提示一次）**实测无信号**（NoMIRACL 42 强答题 0 个全低分、39 题集 9 强答题仅 1 个；
> 强答题与可答题 rerank 最高分分布完全重叠 p50=1.00）——**撤销**，rerank 分维度上相邻证据与答案证据不可分；
> ③ C 面「无证据强答」定案为已关闭，对照 run 0/120＝窗口期异常；
> ④ P1 净新增收窄为两条盲区修补：stats 摘要不算在场（~10 行）+ 知识问答零工具直答视为证据缺席（~20 行，D2 定误伤面）；
> ⑤ 「NoMIRACL 65→85%」收益预期随之撤销——65% 即现役 prompt 软机制后的水位，再往上唯一杠杆是判官式预检
> （每问 +1 次 LLM 调用），是否值得付此成本属 D2 拍板项。

- **信号源（全部已存在，零新耦合）**：`agent_loop._tool_evidence_present()`（已有 helper）+
  相关性 grade（`ANGINEER_EVIDENCE_GRADE`）+ `guard_replaced_*` 留痕（将首次非零）。
- **实现点**：`agent_loop.py` 最终答案判定处，现有逻辑的**镜像分支**——
  现状：模型拒答 + 有证据 → 重试一次；新增：**模型强答 + 证据弱/无 → 注入一次拒答倾向提示，仍强答 → 强制拒答模板**。
- **双条件分档**：检索 0 条非错误 → 直接强制；有候选但全 grade=低 → 提示一次（防误伤）。
- **开关**：`ANGINEER_EVIDENCE_PRESENCE_GATE`（默认 off，A/B 过闸后定默认；登记 `.env.example`）。
- **边界**：改动收敛 angineer-core 循环层，不动 docs-core / 判分器（模块解耦红线）。
- **评审补记（2026-10-05）**：① 闸仅在知识问答路由分支内生效（闲聊/元查询不进镜像分支，防批量误拒）；
  ② 注入提示 turn 的预算记账 D3 定死——仿 `refusal_retry_used` 惯例回退 `attempt_turn`（不占本轮预算），
  并明确与现有拒答重试的互斥关系；
  ③ **拒答机制优先级表（D3 动工前置件）**：拒答相关机制已达 4 层 10+ 支
  （prompt 规则与 grade 软提示 / loop 内 refusal_retry·forced_retrieve / 终局守卫 no_evidence·
  unsupported_reference·tool_error_json·half_refusal_stripped·markers_cleaned / 判分豁免），
  且方向有相反的力——A 面推拒、B 面 01319 型推答、剥头保答。动工前先列优先级表：
  每支机制写明触发条件与让位对象，新增机制必须声明位次。已知直接冲突对须进回归用例：
  **第二档 × `half_refusal_stripped`**（模型写「证据不足，但根据现有材料……」形态——剥头保正文
  vs 第二档强制拒答，同一边界两个相反裁决，先测后合）。

#### 附：拒答机制清单与位次（2026-10-05 梳理，D3 前置件初稿）

判定总原则（P1 落地后）：**证据状态先分流，话术补丁只在分区内生效**——现行守卫是一维
（只看答案话术形态），P1 升为「证据状态 × 话术形态」二维：0 条→强拒（第一档）；
全低分→提示一次→仍强答→强拒（新增第二档）；证据合格→进入现行话术链。

| 层 | 机制 | 触发 | 动作 | 方向 |
|---|---|---|---|---|
| L1 prompt | QA 拒答引导（REFUSAL_ANSWER_TEXT） | 每问 | 软引导 | 推拒 |
| L1 prompt | grade 标签 + relevance_scale（方案①） | `ANGINEER_EVIDENCE_GRADE` 开 | 「全部低分应拒答」软提示 | 推拒 |
| L2 loop | forced_retrieve | 拒答+未调工具 | 代跑检索再问一轮 | 推答 |
| L2 loop | refusal_retry | 拒答+有证据+末段+首次 | 附证据重答一轮 | 推答 |
| L3 守卫 | tool_error_json | 答案=工具错误 JSON | 替换拒答 | 推拒 |
| L3 守卫 | no_evidence（enforce_evidence） | 调过工具+证据文本空* | 替换拒答 | 推拒 |
| L3 守卫 | unsupported_reference | 引用证据外规范/背景 | 替换拒答 | 推拒 |
| L3 守卫 | half_refusal_stripped | 半拒答形态 | 删拒答头保正文 | **保答** |
| L3 守卫 | refusal_kept | 答案即拒答 | 保留+剥无效标记 | 尊重 |
| L3 守卫 | markers_cleaned | 无效 [Kx] 标记 | 剥标记不动答案 | 中性 |
| L4 判分 | is_refusal / is_substantive_refusal + 剥头豁免 | 评测计分 | 行为判定口径 | — |
| P1 新增 | 第二档低分闸 | 强答+全 grade=低 | 提示一次→仍强答→强拒 | 推拒 |
| P1 新增 | stats 摘要不算在场 | 仅摘要、无正文条目 | 按证据弱档处理 | 修盲区 |

\* 现行 `no_evidence` 口径把 `[knowledge_stats]` 摘要也算证据面（agent_configs.py P-1 定版）——
P1 须收窄为「≥1 条带正文的检索条目」，否则空库全零摘要即盲区（对照 run 0/120 的头号嫌疑机制）。

守卫内现行短路顺序（先到先得）：tool_error_json → 信封拆封 → no_evidence →
unsupported_reference → half_refusal_stripped → refusal_kept → markers_cleaned。

冲突对与位次建议（D3 拍板）：
1. **第二档 × refusal_retry**：触发条件互斥（拒答 vs 强答），只需预算记账互斥（补记②）；
2. **第二档 × half_refusal_stripped（架构决定）**：第二档判定**不读话术形态、置守卫链最前**
   （与 no_evidence 并列分流）；剥头收进「证据合格」分区——半拒答+证据合格=现行行为不变，
   半拒答+全低分=第二档接管；
3. **no_evidence × refusal_kept**：现状已定（no_evidence 短路在前），不动；
4. **第二档 × C1 条件指令（未实施）**：C1 先行是前置（立项稿 §3 已定），01319 哨兵题进第二档回归用例。

### P2 DuReader 拆集（零代码，题集 JSON 层）

34 道语料外题反转 `refusal_expected=true`，86 道保持应答；重导 + 复跑（基线报告 §5 P2）。

### P3 harness 变体注册制（轻量，流程层）

借鉴 capture proxy 思想的评测面：任何 harness 行为改动（prompt、守卫、路由参数）登记为具名变体
（配置名 + 判据集 + 基线 run_id），跑完三集才准合入默认。现成设施：LLM_CONFIGS/config_name、
评测 run 体系、`ANGINEER_*` 开关——只缺登记约定。

### 阶段（维持立项稿 D1-D4 骨架）

| 步 | 内容 | 出口 |
|---|---|---|
| D1 诊断 | 三臂新口径重判 + 差集对账 + 01319 扩样 + **新跑臂1/臂2 基准 + 对照 run 溯源**（2026-10-05 评审增补，见立项稿 §2 第 4/5 项） | 病灶占比表；负收益成立与否；验收参照臂读数；溯源结论（溯源不完成，P1 不进 D3） |
| D2 评审 | P0 矩阵 + P1 判据 + 开关默认值拍板 | 业主签字 |
| D3 实施 | P1 闸 + P2 拆集，每步双闸（39 题集 + pos-regress-60）回归 | 行为改动最小化 |
| D4 验收 | 预注册判据全跑（**D1 修订：NoMIRACL ≥85% 线撤销，改 65% 不劣 + 误拒=0 + SQuAD2 不劣（配对）+ 拆集双线 + 01319 哨兵**；定稿属 D2） | 全绿 → 叙事解锁 |

### 明确不做

- **RL / SFT / 训练任何模型**（用户拍板；文章的路线，不是我们的）——且文章自己显示：单 harness 训练与
  multi-harness 训练总分差 1.9pt 在噪声内，训练杠杆的 multi-harness 溢价有限，不改变我们的押注；
- C3 话术稳定性（对照 run 定性：判据层不修，话术层收益封顶）；
- C4 判分口径再收（三集 judge_failed=0，边际为负）。

---

## 7. 关联文档与来源

| 文档 | 关系 |
|---|---|
| `report-refusal-external-baselines-20261005.md` | 证据层：本文全部基线数字与对照实验出处 |
| `req-refusal-guard.md` | 立项层：病灶三面 + C1-C4，本文 P1 即 C5 具体化 |
| `report-refusal-attribution-20260927.md` | 历史层：方案①/②实测、判分口径沿革 |

文章来源（2026-10-05 核实）：
[HF Space 交互页](https://huggingface.co/spaces/AdithyaSK/multi-harness-rl) ·
[r/LocalLLaMA 讨论帖](https://www.reddit.com/r/LocalLLaMA/comments/1wwk49n/the_ultimate_guide_to_multiharness_rl) ·
[第三方 coverage（aisocratic）](https://aisocratic.org/news/hugging-faces-multi-harness-rl-guide-training-small-models-across-agent-interfaces-3twfxa)

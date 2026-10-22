# Harness² × LAB 对表试跑单

日期：2026-10-19　性质：试跑单（不含改造承诺）　上游：[google-research/harness2](https://github.com/google-research/harness2) · arXiv 2610.14224

> **已作废（2026-10-19）**：决定不跑上游流水线，改抄回路。见 `plan-harness2-adoption.md`。本文保留为决策存档，不再执行。

## 0 目的

在同一批 LAB 题、同一判官下，量出「Harness² 形态」与「我们现役 harness」的绝对差距，判断它宣称的 +11.8pt（LAB partial）是否落在我们够得着的量级。

不回答「能不能搬进产品」。那是第 3 步的事。

## 1 预注册判定线（跑前写死，跑后不改）

| 编号 | 条件 | 触发后的动作 |
|---|---|---|
| **J1** | Harness² base 的 criterion ≥ 2× 我们的 17.0%（即 ≥34%） | 差距在 harness 形态，不在 prompt 微调 → 停掉现形态上的话术调参，转形态改造 |
| **J2** | k=1 相对 base 的**配对**提升 ≥ +8pp criterion | 自动改进回路在本任务族有效 → 做 P3（变体注册制自动化） |
| **J3** | base < 20% 且配对提升 < 3pp | 该框架不适合本任务族 → 关线，只留方法论引用 |

阈值依据：我们 100 题报告的 all-pass 95% CI 是 [1.0%, 8.5%]，30 题时是 [1.8%, 21.3%]——小样本 all-pass 没有分辨力。所以判定只用 criterion（逐条通过率，连续量），分组读数一律配对。

## 2 前置闸（缺一条就不跑）

| # | 闸 | 怎么验 | 状态 |
|---|---|---|---|
| 1 | 同一题集 | 我们的 `harvey-firm-knowledge-v1` 001–020 与它 `tasks/<practice-area>/<task>/task.json` 一一对应（题面 + rubric 条数对得上） | 待验 |
| 2 | 同一语料 | 266 matter / 9007 篇；文件数与 matter 清单两侧对账 | 待验 |
| 3 | 同一判官 | gpt-5.5、英文、温度 0、关闭 structured output；用 `HARNESS2_JUDGE_BASE_URL` / `HARNESS2_JUDGE_API_KEY` 指我们网关，先拿一题复判校准 | 待验 |
| 4 | 无 rubric 泄漏 | `task.json` 的 criteria 不进执行器工作区（查 LAB adapter 的 `leak_globs`，实跑后翻一遍 rollout 目录） | 待验 |
| 5 | 执行器断网 | 主机侧禁 `huggingface.co` / `github.com`（作者自己的 release 里就有一次未受指示下载 rubric 的实录） | 待验 |

第 4、5 条任一不过，这批判读作废。

## 3 选样

- **20 题**：`firm-knowledge` 001–020，顺序样本不是随机抽样——故意与我们 100 题报告同源，便于和 17.0% 直接对齐。
- 为什么 20：按中位 5–7 条判据算约 100–140 条；若均值接近全库的 10.5 条（2623/250）则到 200 条，只会更稳。criterion 的 95% CI 约 ±5–7pp，够分辨 J1 的「差一倍」，不够分辨 3pp 级差异——所以 J2 用配对差，不看不配对的绝对值。
- **主读数**：criterion。all-pass 只报不判（20 题里 1 题的摆动就是 5pp）。
- **分段**：题 1–10 / 11–20 分开报。它的 experience library 按领域串行、只读更早条目，前段是冷启动。我们自己 100 题里前 48（12.1%）对后 52（21.4%）就有 9pp 漂移，不分段会把学习曲线误读成框架收益。

## 4 跑法

在 Linux 机器上跑，**不要用部署机**（会抢 nightly 和在跑评测的资源）。

```bash
uv venv --python 3.12 .venv && source .venv/bin/activate
uv pip install -e '.[render]'
harness2-setup lab
harness2-check --bench lab

# 先看选题，不花模型钱
harness2 --bench lab --k 1 --mode parallel \
  --only-domains <practice-area> --max-tasks 20 --dry-run

# 正式跑（含 base 编号执行与 k=1 改进）
harness2 --bench lab --k 1 --mode parallel \
  --only-domains <practice-area> --max-tasks 20

# 判分：--bases 同时给 base 编号，才能拿到配对
harness2-judge --bench lab --k 1 --mode parallel --bases
harness2-report --bench lab --k 1 --mode parallel
```

`--only-domains` 的名目先用 `--dry-run` 打出来的真实目录名，不要照抄文档示例（`antitrust-competition` 只是它的样例）。

## 5 模型入口（唯一的工程风险）

默认只认 Vertex AI ADC。我们的网关是 OpenAI 兼容 `chat/completions` + Bearer。三条路按顺序试：

1. **OpenCode 自定义 provider**（`baseURL` + `apiKey`，openai-compatible 插件）。改 setup 生成的 opencode 配置，看会不会被下次 setup 覆盖。**先花 2 小时试这条。**
2. **Codex substrate + `HARNESS2_CODEX_BASE_URL/API_KEY/MODEL`**。它要 Responses API，我们网关不是——中间得垫 `harness2-bridge`（LiteLLM）。工程量大，只有第 1 条死透才考虑。
3. **兜底：用 Vertex 上的同族模型只跑 base**。结论只对外部模型成立，但能单独验 J1（形态差距），不验 J2。

模型选型：必须选一个**两侧都能调**的。若网关与 Vertex 无交集，第 3 条出局，本轮只做 1→2。

## 6 预算与停止线

- **rollout 数**：20 题 ×（1 次 base + 2 个候选探测 + 1 次改进后跑）≈ **80 次**。
- **墙钟**：按我们 100 题的实测节奏（5 workers，单题中位约 10 分钟）估 **3–4 小时**；它的 probe 是串行同题，实际更慢，按 6 小时排。
- **token 上限**：按预算闸 120k/题 × 80 ≈ **9.6M input**，写死为上限，超了立即停。
- **判分**：约 140 条 criterion × 1 次，成本可忽略，但走同一网关要限流，避免和 nightly 撞。

## 7 不做什么

- 不写 substrate adapter，**不改主仓库任何代码**。
- 不用这批数字对外（n=20、单判官、顺序样本）。
- 不把它的 harness 文件往产品里搬（c1–c8 是 OpenCode 形态，我们的骨架在 Python 里）。

## 8 产出物

一张表 + 一段结论，只回答 J1/J2/J3 哪条触发：

| harness | criterion | all-pass | 题 1–10 | 题 11–20 |
|---|---|---|---|---|
| 我们现役（100 题基准） | 17.0% | 3.0% | — | — |
| Harness² base | ? | ? | ? | ? |
| Harness² k=1 | ? | ? | ? | ? |

## 9 待确认（今天可查完，查完再排期）

1. `harvey-firm-knowledge-v1` 是上游 LAB 的某个 practice area，还是我们自建的子集？决定第 1 道闸能不能过。
2. 它 checkout 的 `tasks/<area>/<task>/task.json` 里，rubric 是否落在执行器可见目录。
3. 网关能不能被 OpenCode 当 openai-compatible provider 接——拿一题试，不通就转第 2 条路。

# Harness² 内化方案

日期：2026-10-19　上游：[google-research/harness2](https://github.com/google-research/harness2) · arXiv 2610.14224
取代：`plan-harness2-lab-probe.md`（对表试跑单，2026-10-19 决定不跑）

## 0 决策：不跑上游流水线

三条理由，按权重排：

1. **缺 Vertex 工程。** 全仓没有任何 `GOOGLE_CLOUD_PROJECT` / gcloud / ADC 配置。跑起来要先开 GCP 项目、配额、服务账号，再挂 9007 篇语料到它的 task 目录。为一次对表开这个账单不值。
2. **可编辑面不重叠。** 它改的是 OpenCode 的 c1–c8 文本树；我们的骨架在 Python（路由、检索、rerank、守卫判定）。跑通了也不动我们一行代码。
3. **唯一收益是对表数。** 而这个数只回答「形态差多少」，不回答「下一步改哪里」。

信论文可信，不等于我们手上能落数。不跑，就没有自己的读数——所以对外引用一律标【它声称】。

## 1 抄什么，不抄什么

| 机制 | 决定 | 理由 |
|---|---|---|
| 提议—探测—组合 | **抄** | 我们换变体要改代码再单独跑，同题对比做不了 |
| 无金标选择 | **不抄** | LAB 有 rubric，判据比行为对比硬 |
| 按领域经验库 | **抄（轻量）** | 我们已有「未采纳实验」表，缺的是结构化条目 |
| c1–c8 文件树 | **抄一半** | 只外置 prompt / 守卫规则 / 工具描述，pipeline 冻结 |
| OpenCode / Codex 执行器 | 不抄 | 我们跑自己的服务 |

## 2 四步

### 第 1 步：prompt 版本可运行时钉住（半天）

现状：`register()` 已登记 `v7`–`v18`，但 `load()` 只认 `latest`，换版本要改常量再重启。

改法：`load()` 支持环境变量钉版本；`versions()` 返回**生效**版本而不是最新版本；补一条单测。

DoD：`ANGINEER_PROMPT_PIN=agent_configs.qa_system_prompt=v17` 启动后，`versions()` 报 `v17`。

### 第 2 步：同题 A/B 探测（1 天）

`data/scratch/harvey-lab/tools/run_angineer_arm_par.py` 加 `--harness-variant`，同一题跑 A、B 两遍；新增 `scripts/probe_diff.py` 输出行为 diff：

- 工具调用序列差异；
- `doc_read` 覆盖了哪些 matter / 哪些页；
- 最终答案引用了哪些证据；
- 逐条判据命中差异。

DoD：10 题 × 2 变体一张表，能量出「哪条编辑改变了行为」。

### 第 3 步：把提议交给模型（3 天）

输入：可编辑文件 + 任务题面 + 第 2 步的轨迹；输出：候选 patch + 修改理由。

校验闸：prompt 单测通过、diff 非空、不碰 pipeline 文件、不引入新工具。

DoD：k=2 候选，人在回路采用/丢弃，采用记录进经验库。

### 第 4 步：形态实验（1 周，可与前几步并行）

理由：criterion 现在 17%，按 k=5 的合取算术要到 ~72% 才有 19.2% 的 all-pass。这个量级提示词补不出来——它自己的 LAB harness 也不是调提示词调出来的，是「文件树 + 逐篇读 + 子代理」。

做法：给 LAB agent 加「按 matter 遍历 + 2 个子代理分头查」，10 题配对。

DoD：criterion 配对差 ≥ +5pp 才继续投。

## 3 判据（预注册）

- 第 2、3 步：配对 criterion，10 题，**+5pp** 为门槛。
- 第 4 步：同门槛，另看 `doc_search` 使用率与逐条命中分布。
- 所有对外引用标【它声称】，直到我们自己跑出数。

## 4 不做

- 不为对表开 GCP 项目。
- 不搬 c1–c8 文件树，不引它的 harness 文件。
- 不用 n=10 的读数对外。

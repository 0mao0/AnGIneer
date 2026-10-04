# 需求票：夜间测试中断可见性与断点续跑（四 bug 合一）

- 状态：已评审（2026-10-04 建，当日评审后补 B2 映射规则/人为停止档归宿、B3 hint 生命周期三处歧义，验收同步加锁）
- 来源：2026-10-04 晚实踩全链路（本票 §1）
- 涉及：`evals-core`（sweep/archive/nightly pipeline）、`aichat-api`（evals_routes/nightly_control）、`admin-web`（EvalNightlyPanel）

## 0. 一句话

nightly 被部署/重启砸掉后，成绩库里留下永久「运行中」的幽灵行、页面上留下「损坏」的无名行，续跑机制明明存在却对用户不可见——修所有权判定的根因，把「中断/续跑中」变成一等状态。

## 1. 事故经过（证据链，2026-10-04）

| 时刻(北京) | 事件 |
|---|---|
| 16:08:07 | 手动 nightly 起跑 `run-061266cfa555`（1040 题），派发留痕 `last_dispatch` ok=true |
| 19:52:20 | 另一会话改服务器 .env，按 SOP `docker compose up -d` 重建 aichat-api（未检查有 run 在跑）→ 进程内流水线死亡，停在 869/1040（completed 869 / pending 168 / 卡 running 3） |
| 19:52+ | 启动清扫（`evals_routes.py:72` → `suite_runner.sweep_interrupted_runs`）应盖章回收该 run——**空转**，行永远 status=running |
| 20:1x | 夜间页该行渲染成「损坏」（无时间无时长）；下午进程活着时正常显示「运行中」 |
| 20:31 | 临时手术：照 sweep 原逻辑经 `result_store.cancel_run` 手工盖章 `interrupted_by_startup_sweep`（correct 758/wrong 107）；`_find_resume_candidate` 演练命中 |
| 20:35 | 用户点「立即运行」→ 页面先显示种子行「20:35 / 0 分钟 / 题量空」，形态与全新起跑不可区分，被误读为重跑；数秒后探测命中、切回原 run（16:09 起、870/1040 续涨）——续跑成功，体感失败 |

**临时手术是止血，B1 修复落地前，下次部署砸 run 会原样复发。**

## 2. 四个 bug 与根因链

### B1（根因）启动清扫在容器化部署下永不触发

- 判定 `suite_runner.py:799` 用 `_pid_alive(owner_pid)` 保护多实例；`owner_pid=os.getpid()` 写入（`result_store.py:736/769/782`，分别对应 create_run / reset_run_for_resume / restart_run_for_retry）。
- docker 容器主进程恒 PID 1（实测 `/health` pid:1）；新容器里 `os.kill(1,0)` 恒成功 → 判「别的实例还活着」→ **回收分支永不执行**。
- 09-06 修复（防多实例误杀 53/487 事故）的 pid 语义诞生于同机多进程时代，容器化后 pid 复用使守卫必然误判。
- **修法（不引入 boot 列/心跳，最小 diff）**——清扫判据改为判定表：

| run 在本实例内存（`is_running_here`） | owner_pid vs 本进程 | owner_pid 存活 | 判定 |
|---|---|---|---|
| 是 | — | — | 活体，不动 |
| 否 | **相等（pid 复用）** | — | 幽灵 → 清扫盖章 |
| 否 | 不等 | 死 | 幽灵 → 清扫盖章 |
| 否 | 不等 | 活 | 他实例活体 → 不动（保留 09-06 保护） |
| owner_pid=0 历史行 | — | — | 照旧回收（现行行为） |

容器场景 owner_pid=1==新进程 self → 第二行命中 ✓；开发机多实例：活体走第四行保护 ✓。

### B2 夜间页无「中断」态，一律显示「损坏」

- `archive.read_entry`（`archive.py:250-258`）：槽位缺 nightly.json / JSON 不可读 → `state=corrupt`；UI `EvalNightlyPanel.vue:208` 状态表只有 运行中/通过/回归/失败/损坏。
- 中断槽位（有 B 层产物、无结论文件、DB 行=cancelled+中断章）被误标「损坏」——「损坏」应保持只表示**结论文件真不可读**。
- 修法：`list_entries` 组装时读 eval_run（同库直读），`cancelled && summary_scores.interrupted_by_startup_sweep` 的槽位 → `state=interrupted` + `started_at`/已完成数（DB 口径）；UI 加「中断」橙色 tag（状态表加一行）。
- **slot ↔ run 映射规则（2026-10-04 评审补充）**：中断槽位没有 nightly.json，slot 名是北京时间 `HHMM-6hex`（`paths.new_run_slot`），本身不含 run_id，必须定反查规则——
  - 候选集：nightly 配置 dataset 下 `status=cancelled` 且 summary_scores 带中断章的 run，其活跃区间 `[started_at, completed_at]`（UTC naive → 北京）覆盖 slot 日期即候选；
  - 同日内多个 corrupt slot 与多个候选按 started_at 时间序一一配对（同日多中断是稀有形态，定序配对保证确定性）；
  - **无候选 → 维持 `corrupt`**（真损坏语义不稀释）；
  - 不能用「slot 前缀 HHMM == run 开跑分钟」匹配：素材检查先于评测建档（`pipeline.py:421` 先跑 `_material_health`），run 建档在派发分钟之后；且 `reset_run_for_resume` 保留原 `started_at`（`result_store.py:764-766` 注释），续跑形态的 run 开跑时刻可能与当档差数小时甚至跨日。
- **人为停止档的归宿**：`stop_pipeline` 走 stopped 收口不落档（`pipeline.py:455-463`）、DB 行是无章 cancelled（`_finish_cancelled` 不盖章）——**不归入 interrupted，维持 corrupt**。口径一致性：页面上「中断」= 可断点续跑，与 B3 弹框提示（只认章）严格同判据，避免「页面说中断、弹框说没有」割裂。注意 `EvalNightlyPanel.vue:241` 现有「评测中断，未出结论」文案由 error/corrupt 共用，改状态表时别让 error 档丢文案。

### B3 续跑机制存在但不可见；种子行把续跑伪装成重跑

- 续跑本身已实现且够用：10h 窗口（`pipeline.py:319`）、只认 cancelled+章、`caliber_fp` 逐字相等守卫（`pipeline.py:322-345`）、「立即运行」自动探测（`pipeline.py:426`）。**不动这套判据**（跨口径缝合=红线）。
- 可见性缺口两处：
  1. 种子行（`nightly_control.py:226` running_entry）：派发间隙时间=按下时刻、无进度，与全新起跑无差别。修法：dispatch 前探测到 resume 候选即写入模块级 `_resume_hint`，种子行带 `resuming_from=run_id、already_done=N`，行文案显示「续跑中（已完成 N/总）」；探测完自然被真实 run 行接管。
     - **`_resume_hint` 生命周期（2026-10-04 评审补充）**：一次性消费——真实 run 行一出现（`running_entry` 里 `run is not None`）hint 即不再参与渲染；`_execute` 的 finally 兜底清空，防探测落空/异常后残留导致下次**全新**起跑误显「续跑中」。
     - launch() 是 async，探测走 `asyncio.to_thread`（同 `pipeline.py:426` 姿势）。
     - 一致性兜底：launch 探测与 pipeline 内部 `_find_resume_candidate` 是两次独立调用，窗口边界上可能不一致（种子说续跑、实际全新跑）——种子行文案只是提示语，以 pipeline 实际派发为准，不构成行为契约。
  2. 「立即运行」确认弹框（`run_plan`，`evals_routes.py:587`）：预览里加一行「检测到 10h 窗口内中断的同类评测（N/M 已完成），本次将断点续跑」；无候选则不显示。
- 窗口外/无章的中断行：日常测试列表已有「继续评测」按钮（sweep 文档字符串所述），夜页不重复做入口，B2 的中断行文案指路即可。

### B4 日常测试列表僵尸行（随 B1 自动痊愈）

- B1 修复后孤儿行启动即 cancelled，09-06 的「评测中假进度轮询」教训在容器侧不再复现。只补回归锁，不单独施工。

## 3. 已评估否决

- **boot 指纹列 / owner_start_ts / 心跳表**：判定表第二行（pid==self → 幽灵）已覆盖容器形态与同机多实例，加列加心跳是多余复杂度；若未来出现「同机两容器共享 pid namespace」再议。
- **nightly 跨进程续跑/任务队列**：成本不成比例，10h 窗口+手动点击已验证够用。
- **放宽 10h 窗口或跨口径续跑**：违反预注册纪律（口径变了已完成题不可比），维持现状。

## 4. 验收标准

- A1（B1）行为锁：按 §2-B1 判定表逐行写测试——①容器形态（owner_pid=1、不在内存）→ 清扫盖章、correct/wrong 与明细一致；②本实例内存 run → 不动；③模拟他实例（pid 活着且≠self）→ 不动（防 53/487 复发）；④owner_pid=0 → 回收照旧。
- A2（B2）：中断槽位列表返回 `state=interrupted`+时间+已完成数；结论 JSON 损坏仍 corrupt；**无章 cancelled（人为停止档）仍 corrupt**；corrupt slot 无任何带章候选 run 时维持 corrupt（映射规则空配不硬凑）；前端状态表含「中断」。
- A3（B3）：带续跑候选时——种子行含「续跑中（已完成 N）」、确认弹框含续跑提示行；无候选时两者均与现状逐字一致（不添噪）；**探测落空后再次全新起跑，种子行不残留「续跑中」字样（hint 一次性消费）**。
- A4（B4）：A1 落地后重启容器，日常测试列表无永久「评测中」行。
- A5 回归面：nightly 现有 pipeline 测试全绿；`_find_resume_candidate` 判据零改动（守卫测试在 A3 断言弹框只读不改派发）。

## 5. 工作量与拆包

| 包 | 文件 | 量 |
|---|---|---|
| P0 B1 判定表＋锁 | suite_runner（一函数）＋tests | ~0.5h，可独立回退，建议先行 |
| P1 B2 中断态 | archive.py＋evals_routes＋EvalNightlyPanel | ~2h |
| P1 B3 续跑可见 | nightly_control＋run_plan＋EvalNightlyPanel | ~2h |
| 合计 | | 半天级，新增测试 ~15 例 |

## 6. 票外（运维纪律，不入代码）

重建 aichat-api/docs-api 容器前先看一眼 nightly/评测是否在跑（`GET /api/evals/nightly/settings` 的 `running` 字段或页面首行）；两会话共改服务器 .env 的场景今晚已实踩一次。是否写入 AGENTS.md 由业主定。

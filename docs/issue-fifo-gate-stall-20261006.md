# 缺陷立票：FIFO 资源闸门排队期取消后「序号不让位」（2026-10-06 实踩）

> 状态：立案待修。复现路径与代码证据均为 2026-10-06 OfficeQA 191 册入库驱动实测。
> 关联：`docs/plan-retrieval-speedup-v3.md`（闸门设计未在此文档；FIFO 闸门实现只在代码里）。

## 1. 症状

批量解析期间，用户/脚本取消一个正在**排队等资源**的解析任务后：

- 该任务在 `parse_records` / `eval_run` 侧标成 cancelled，但**闸门序号不释放**；
- 后续排队任务全部卡在 `should_wait=True`，闸门整体停摆，只能重启 docs-core 进程恢复。

## 2. 根因（代码证据）

`services/docs-core/src/docs_core/parse_pipeline.py`：

| 位置 | 事实 |
|---|---|
| `_FifoGpuGate.acquire`（:557-591） | 排队循环里每 `poll_interval` 轮询 `cancel_check()`；抛 `ParseTaskCancelledError` 时只**登记 `_cancelled_seqs` 让位**（:586-590），**令牌从未 acquire 成功、`release()` 不会被调**——设计如此 |
| `ParseOrchestrator.cancel_parse_task`（:1115-1138） | 只 `request_parse_task_cancel` + 置 `_cancelled[task_id]` + `parser.cancel()`。**若取消发生在任务进入 raw_parse/popo/图描述之前（还在 convert 或更早），闸门序号根本没登记**：`skip(seq)` 只在 `mineru_gpu_slot`/`popo_inference_slot`/`figure_describe_slot` 的取消异常路径上才会被触达（:249/:317/:474 的 with 块内） |
| `_FifoGpuGate._skip_cancelled_locked`（:534-538） | 跳号逻辑本身正确：`_cancelled_seqs` 命中 `_next_seq` 时能连跳。**前提是取消发生在 acquire 内部**；发生在 acquire 之前（任务还没排到闸门）时 `skip()` 无人调用 |

即：**取消通知机制（`_cancelled` 集合 + `_raise_if_cancelled`）与闸门序号让位（`gate.skip`）只在 with 块异常路径上相连；「取消在进闸门前」这条时序线上没有任何一方负责让位。**

## 3. 复现条件（低频但破坏性大）

- 并发窗口 >1（`MINERU_MAX_CONCURRENCY>1` 或 4 个同型驱动并发）；
- 用户对「还在 convert/排队」的文档点取消（批量导入时很常见——大册在 convert 卡 10+ 分钟时用户会先砍后面排队的册）；
- 该文档的后续依赖链（同批 popo/图描述依赖 raw_parse 产物）随之全部悬空。

## 4. 修复方向（待拍板，暂不动手）

1. **首选**：`cancel_parse_task` 里取消成功路径上直接 `gate.skip(task_arrival_seq)`（三闸门各查自己阶段的 seq），不等 with 块异常传播——让位与取消同事务，断掉时序窗口；
2. 兜底：闸门侧给 `_next_seq` 加空洞检测（长期无人 acquire 队首 → 标记僵尸槽 + 告警日志），防同类时序再出现时静默停摆；
3. 无论选哪条，`EVAL_CONCURRENCY` 与 `MINERU_MAX_CONCURRENCY` 属**评测/解析共享 GPU 链路**的并发闸，改哪个都要带回归：FIFO 顺序性测试（先 submit 后 cancel 的序号必须可跳过）+ 闸门停摆哨兵测试。

## 5. 影响面

- 本地 191 册入库驱动 10-06 23:53 起曾整链停摆 40+ 分钟，即此雷（当时用重启 docs-core 止血）；
- 生产侧同样存在（同一份 parse_pipeline.py），但生产解析为人工触发、批小，未观测到；
- 与 nightly/评测池无关，不影响 133 正跑判定。

# 2×2 裁决实验预注册（模型 × Schema 契约，plan-ls-routing §5.2）

- 日期：2026-11-07（跑前写死；跑后只许在「结果」节追加，不得回改判定规则）
- 决策问题：P1（运行时回答分型分类器与五型路由体系）建不建
- 状态：预注册落稿，实验未启动

## 1. 四臂矩阵（唯一变量 = 模型 × Schema 契约）

| 臂 | 模型（answer config_name） | Schema 契约 | 说明 |
|---|---|---|---|
| A | Qwen3.6-35B-A3B | 自由文本 | 当前模型、无结构化 |
| B | Qwen3.6-35B-A3B | Schema | 当前模型、结构化 |
| C | Qwen3.8-Flash-Next | 自由文本 | 新模型、无结构化 |
| D | Qwen3.8-Flash-Next | Schema | 新模型、结构化 |

Schema 契约（§5.2 最小契约）＝通用结构化输出（S1 行协议+引文校验）＋聚合题代码统计（S2，
仅限有预注册规格的 016/041——规格自动化属 P1，本实验不扩）。**四臂同证据**：预读上下文
由 Arm A 落盘、B/C/D 经 `ANGINEER_ENUM_CONTEXT_DIR` 逐字节复用；同预算（QA_MAX_TURNS=12、
200k）；同判分通道（rubric 内部通道）。

## 2. 题集（31 题，规则锁死）

task 001–030 升序（206 判据、其中聚合题 10 道：002/005/007/014/016/017/018/022/025/030）
∪ {041}（预注册聚合规格题强制入选，23 判据）＝ **31 题、229 判据、11 道聚合题**。

判定规则相关的子集：聚合子集 = 016/041（有 S2 代码统计）；非聚合题 20 道。

## 3. 判官（全臂统一：ds-flash-off）

- 与两个被测模型（3.6/3.8）均独立，无自判风险；探活 OK（JSON 遵从、0.73s）。
- 经 POST `judge_config_name=ds-flash-off` 显式指定（run 级判官绝对优先，已核实
  `_resolve_judge_candidates` 无自判拦截——本预注册即约束载体）。
- **判官审计**：跑后按逐条 `judge_used` 过滤，判官 ≠ ds-flash-off 的条目剔除分母并
  如实报数；判分失败（fallback）条目按 skipped 退出分母单独呈报。

## 4. 轮次与池化口径

- 每臂 31 题 × 2 轮（第 1/2 轮独立 run），四臂共 **248 run**。
- 池化：同臂同题同 criterion 两轮通过数（0/1/2）→ 条目均值比较；micro（229 条池）+
  macro（31 题逐题均值）双报；聚合子集（016+041，37 条）单列。

## 5. 判定规则（锁死）

1. **D−C ≥ +12 条且两轮方向一致** → Schema 对新模型仍有增量 → 按 §5 建 P1；
2. **D−C ≤ 0 且 B−A ≥ +12** → 确认弱模型补丁 → 停通用五型路由，只留确定性件；
3. S1 类收益消失而聚合/计算类仍有收益 → 只留聚合/计算/校验，不做完整五型体系；
4. 池化后仍不足 +12 → 证据不足，维持现状（不建 P1，确定性件保留）；
5. 主判据在 229 条池；±12 条门槛 ≈ 5pp，已对齐单轮 ±5 题/12% 噪声地板的两轮池化容差；
6. 无论裁决结果，施工主线确定性件（对账/代码统计/引用/数值槽/安全终态）均保留。

## 6. 执行手册（四段后台，段间重启 aichat 切 env）

| 段 | env 增量 | run 配置 |
|---|---|---|
| A | ENUM_PREFETCH=1, PREREAD=1, STRUCT/AGG=0, DUMP_DIR | config=Qwen3.6-35B-A3B, judge=ds-flash-off |
| B | +CONTEXT_DIR, STRUCT=1, AGG=1+SPECS | config=Qwen3.6-35B-A3B |
| C | STRUCT=0, AGG=0（保留 CONTEXT_DIR） | config=Qwen3.8-Flash-Next |
| D | STRUCT=1, AGG=1 | config=Qwen3.8-Flash-Next |

每臂 62 run（31×2 轮），`run_2x2_arm.py --config --judge --label --rounds 2`；
run_id 清单落 `data/scratch/harvey-lab/2x2/<label>.json`。
启动前检查点：Arm A 首题 manifest 核 model/judge/dump 三件套；Arm B 核 CONTEXT_DIR
复用日志与 struct 渲染。异常（判官大面积失败、run 挂死）即时停批。

## 7. 结果（跑后追加）

- （待实验）

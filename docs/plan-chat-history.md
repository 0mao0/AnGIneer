# 计划：聊天历史 B 路线（服务端历史 + 游客档 + 会话持久化）

> 状态：**待启动**（2026-09-17 定稿方向，代码未动）
> 关系：与 `docs/plan-service-surface-and-embedding.md` 同族——C1「库化准备性重构」与 §5 触发式项
> （C2 依赖闭包发 PyPI / QA 引擎库化）**均未触发**，故本计划只守同样的纪律：
> **不新建独立仓库、不发布新包、不改依赖闭包**，只保证目录与依赖方向正确，将来搬迁只是移文件。

---

## 0. 决策记录（2026-09-17 定稿，不再讨论）

| # | 决策 | 依据 |
|---|---|---|
| D1 | 走 **B 路线**：历史搬服务端，DB 为真相源（跨设备可见） | 用户要求 |
| D2 | 游客档：免密进站、只能问默认知识库；**满 30 轮（user+assistant 算 1 轮）硬拦，必须登录** | 用户明确 |
| D3 | **游客消息也入库**（匿名内容留存 90 天，已知取舍） | 用户明确 |
| D4 | 保留期：**消息内容 90 天**，且存**全量**（含 citations / 思考过程） | 用户明确 |
| D5 | 审计表本期做：`run_id` / 模型 / 耗时 / 状态 / 错误 | 用户要「查问题在哪里」，只存文本查不了 |
| D6 | `owner_key` 统一取 `resolve_pool_owner()` 的返回值（`u:` / `k:` / `g:`） | 与池 key 同一身份来源；游客 cookie 落地后匿名桶由 `ip:` 升级为 `g:`，顺带消掉「同 NAT 撞池」残留 |
| D7 | **两层解耦**：存储＝引擎协议的一个插件；HTTP/产品面＝一个包（`store/` + `routes/`） | 见 §3 |
| D8 | **写入分工**：服务端在 run 结束写 role/content + 审计（权威）；客户端 PUT 只补展示字段 | 上下文与审计不能由客户端决定 |
| D9 | 非目标：自助注册、内容审核、多副本无状态化、真实 token 计量 | 与既有边界一致 |
| D10 | **seq 唯一权威在服务端**：`chat_messages.seq` 由服务端分配，SSE `AgentEvent` 帧携带 `msg_seq`；客户端 PUT 只允许携带服务端已下发的 seq + 展示字段补丁，未知 seq 一律拒（否则按 seq 合并会把两条消息并成一条，且违反 D8） | 审核发现：不写死这条，PUT 合并语义不成立 |
| D11 | **回灌只在池内新建 session 时做一次**：`get_agent_session` 命中池不灌（内存 `AgentSession.history` 已是真相）；hydration 按 `(owner, session_id, scope_hash)` 过滤，跨 scope 的消息不灌（池 key 本就以 scope_hash 隔开会话） | 审核发现：不写死会双写双序、跨 scope 串上下文 |
| D12 | **30 轮闸可被清 cookie 绕过**（新 `guest_id` = 新 `g:` 桶 = 新 30 轮；claim 后 `u:` 桶从零起算）——与 D3 同列「已知取舍」，不当作 bug 追修 | 审核发现：防护目标是引导登录而非强身份闸门 |
| D13 | **回灌全量、不做轮次裁剪**：池内新建 session 时把该 scope 的历史全量灌回（与 D4 存全量口径一致）；引擎内存 history 现有的不限轮次行为本期不动（属独立议题） | 审核发现：「内存不限轮次、跨重启只灌 10 轮」两个口径互相矛盾，择一取最简 |

---

## 1. 数据模型：`data/chat.sqlite`

DAO 照 `services/shared/src/shared/user_model.py` 形态（函数式 DAO + WAL + `init_db()` + try-ALTER 加列）。

| 表 | 字段 | 说明 |
|---|---|---|
| `chat_sessions` | `owner_key, session_id, scene, library_id, doc_ids_json, scope_hash, title, created_at, updated_at`；PK `(owner_key, session_id)` | 会话元信息；`scope_hash` 与引擎池 key 同算法（库+排序 doc_ids 的 sha1 前 8 位），会话换库/换文档集即新 hash |
| `chat_messages` | `owner_key, session_id, scope_hash, seq, role, content, meta_json, created_at`；查询键 `(owner_key, session_id, scope_hash)` | `meta_json` 存展示全集：citations / thinking_trace / strategy / timings / 停止与错误标记；`seq` **服务端唯一权威**，单调递增，SSE 帧下发（见 §3 硬约束 3） |
| `chat_runs` | `run_id PK, owner_key, session_id, model, latency_ms, status, error, created_at` | 审计：查「为什么错/慢/报错」 |
| `chat_guests` | `guest_id PK, created_at, last_seen_at, claimed_by_user_id`（`UNIQUE(guest_id, claimed_by_user_id)` 语义先到先得：一次 claim 只认一个账号，多浏览器重复 claim 幂等返回首个认领者） | 游客身份与认领状态 |

落 `data/` 卷（`docker/docker-compose.yml:63-65` 已挂），跨发版存活。

---

## 2. 接口

| 端点 | 用途 | 鉴权 |
|---|---|---|
| `POST /api/chat/guest` | 签发 HttpOnly `ag_guest_id`（幂等） | 无 |
| `GET /api/chat/sessions?library_id=` | 会话列表（updatedAt 倒序，后端复刻 `deriveTitle` 与 50 上限） | 登录按 `u:`，游客凭 cookie 只读自己的 `g:` |
| `GET /api/chat/sessions/{id}` | 消息全集（AIChatMessage 形状） | 同上 |
| `PUT /api/chat/sessions/{id}/messages` | 客户端快照：**只补展示字段**——请求体为 `[{msg_seq, meta_patch}]`，仅接受服务端已下发过的 `msg_seq`（见 D10），不写 role/content、不允许自带序号 | 同上 |
| `DELETE /api/chat/sessions/{id}` `DELETE /api/chat/sessions?library_id=` | 用户删除权（单条 / 清空） | 同上 |
| `POST /api/chat/sessions/claim` | 登录后把当前 cookie 的 `g:` 会话改挂 `u:<user_id>`（老账号即「会话 +1」），`chat_guests.claimed_by_user_id` 落痕。**不杀在跑 run**；落库 owner 以会话行当前归属为准（见 §8 竞态说明） | 需登录 |
| `POST /api/chat/agent` 前置闸 | 该 owner 的 user 消息数 ≥ 30 → 403 + `code=login_required`（前端据此弹登录） | — |

---

## 3. 解耦设计（本次必须守的纪律；不增加工时，只约束目录与依赖方向）

```
angineer-core（引擎）        定义协议 LLMClient / Retriever / ToolProvider / HistoryStore
        ▲                    ← 引擎不认识 sqlite、HTTP、游客 cookie、保留期
        │ 实现协议
services/chat-history/     一个包、两层目录，pyproject 照 angineer-core 形状
   ├─ store/    sqlite 实现（实现引擎协议）+ 保留期 GC
   └─ routes/   FastAPI router（§2 的表）+ 游客 cookie + 30 轮闸 + claim
        │
        └─ aichat-api 组装：include_router(...) + 注入 store + 注入策略参数
```

引擎侧协议保持最小，多一个方法都是负担：

```python
class HistoryStore(Protocol):
    def load(self, owner: str, session_id: str, scope_hash: str) -> list[AgentMessage]: ...
    def append(self, owner: str, session_id: str, messages: list[AgentMessage], run_meta: dict) -> None: ...
```

四条硬约束：

1. **不 import 引擎实现**：`chat-history` 只依赖引擎的协议与 sqlite；不 import `docs_core`（这条也是 `docs/plan-service-surface-and-embedding.md` C1 的同一纪律）。
2. **策略注入而非写死**：30 轮阈值（`ANGINEER_GUEST_ROUNDS`，默认 30）、是否强制登录、保留天数（`ANGINEER_CHAT_RETENTION_DAYS`，默认 90）全走参数/env，不硬编码在端点里。
3. **契约冻结 + 版本号**：SSE 帧（`AgentEvent`）加 `frame_version`（首帧字段或响应头）与 `msg_seq`（服务端消息序号，D10 的客户端 PATCH 依赖它）；前端 `AIChatTransport`（`packages/aichat-ui/src/api/types.ts` 已有）作为对外契约固定下来。今天帧 TS 类型与 Python 类型靠人肉同步，无版本号——别人升级必炸。
   - 注：`QueryRequest.history` 是死字段（`main.py:173` 声明后全仓库无读取点），客户端从不发历史——上下文 100% 来自服务端内存池。本期顺手删该字段，历史真相源单一化。
4. **发布边界**（现在不发，登记触发式，与既有 §5 一致）：

| 产物 | 现在 | 触发条件（同既有 §5） |
|---|---|---|
| 前端 `angineer-aichat-ui` | 已上架 npm 0.1.9 | — |
| 前端「参考 transport」导出 | 不做（宿主自备） | 有外部消费者时 |
| 后端 `angineer-chat-history` | **只做 in-repo 模块** | 第一个真实嵌入需求 |
| 引擎 `angineer-core` 去 docs-core 硬依赖 | 不做 | 随 C2 / QA 引擎库化（§5 已登记「RetrievalPort 抽象收尾」） |

---

## 4. 前端（apps/user-web）

| 项 | 改动 |
|---|---|
| 游客放行 | `App.vue:5` 去掉「未登录即全屏 `AuthGate`」的硬门，加「以游客身份开始」；进入时调一次 `POST /api/chat/guest` |
| 游客态收敛 | 隐藏库选择器（恒「默认知识库」）、顶栏（`ChatTopBar.vue:46` 现显示 `未登录`）改为「登录」按钮 |
| 30 轮闸 | 收到 `login_required` 403 → 弹登录页并说明原因；**当前对话不丢**，登录后接着聊 |
| 登录后并入 | 登录成功后自动 `claim` + 刷新历史抽屉（游客期间聊的对话出现在账号里，老账号 +1 条会话） |
| 历史实现切换 | `apps/user-web/src/composables/chatHistory.ts` 三个函数签名不变、改 async HTTP（该文件 L1-5 就是为此预留的替换点），localStorage 降级为缓存 |
| 存量导入 | 首次登录时按 id 差集导入 localStorage 存量（幂等） |
| 活跃会话 id | 按库持久化 `ag_active_session_v1`，挂载复用、仅「新建对话」轮换；顺带修 `ChatHome.vue:194-200` 与 `useAIChat.startNewChat` 双生成 id 互相覆盖 |

---

## 5. 分期（每步可独立验收）

| 步 | 内容 | 验收 |
|---|---|---|
| 1 | 建库 + `HistoryStore` 协议 + 服务端写入 + 回灌（D11：仅池内新建时灌一次、按 scope_hash 过滤、全量不裁）+ 删 `QueryRequest.history` 死字段 | 重启 aichat 容器 → 同会话续聊模型能引用前文 |
| 2 | 列表 / 详情 / 删除 / 快照 PUT / claim | 跨设备可见；登录后会话 +1 |
| 3 | 游客 cookie + 30 轮闸 + 前端游客入口 | 无登录提示进站；第 31 轮被拦并提示登录 |
| 4 | 保留期 GC（90 天）+ `scripts/chat_db_gc.py` | 过期行被清；用户删除立即生效 |
| 5 | 前端历史切 HTTP + 存量导入 + 活跃 id 持久化 | 刷新页面不失忆；老浏览器历史可导入 |

---

## 6. 验收与测试

- **手工核心链路**：游客进站 → 聊 3 轮 → 登录 → 会话出现在账号 → 换设备可见 → 重启容器仍能续聊 → 第 31 轮被拦
- **pytest**：`HistoryStore` 协议两方法；回灌仅在池内新建时触发一次（池命中不灌）；行级隔离（跨 owner 查不到）；跨 `scope_hash` 不互相灌；claim 改挂与 +1 语义（含**在跑 run 竞态**：claim 中途写入不丢消息、不改挂本 run）；30 轮闸边界（29/30/31）；PUT 未知 `msg_seq` 被拒；保留期 GC
- **回滚注**：步骤 1 上线后若回滚代码，行为退化为今天的内存池（DB 里的历史仍在，重新部署新代码即恢复），无数据迁移风险
- **vitest**：`chatHistory` HTTP 实现、claim 后刷新、403 `login_required` 分支、活跃 id 持久化
- **回归**：评测走进程内 `run_policy_query`（`evals_core/runner/_query_helper.py:47-49`「不走 HTTP」），零影响；跑一次小数据集确认
- **安全回归**：匿名仍只能问 `default` 库（v0.2.66 已上线的那道闸不得被游客 cookie 改动破坏）

---

## 7. 待确认的默认取值（不同意就说，否则按此实现）

| 项 | 默认 | 备选 |
|---|---|---|
| 30 轮口径 | **累计**（每个游客 cookie 一辈子 30 轮） | 每日 30 轮（可做成 env） |
| 游客历史抽屉 | 可见（凭 cookie 读自己的 `g:` 桶） | 只服务端存、界面不展示 |
| 审计表 `chat_runs` 保留 | 与消息同为 90 天 | 单独更长（如 180 天） |
| `chat_guests` 与认领记录保留 | 与消息同为 90 天（认领记录可能含审计价值，过期随 GC 清） | 单独更长（如 180 天，与 `chat_runs` 同档） |
| localStorage 存量导入 | 做（首次登录、按 id 去重） | 不做，从空开始 |

---

## 8. 竞态与边界说明

- **claim × 在跑 run**：claim 只改 `chat_sessions/chat_messages` 的 `owner_key` 归属与落 `claimed_by_user_id`，**不取消在跑 run**。在跑 run 持有的旧 owner（`g:<id>`）仅用于鉴权；**落库 owner 以 `chat_sessions` 行当前归属为准**——写入前先按 `session_id` 查会话行，行已被 claim 搬走则跟随新 owner，天然不产生孤儿行。验收对应 §6 的 claim 竞态 pytest。
- **PUT × 在跑 SSE**：客户端快照可能在 run 进行中到达。因 PUT 只接受服务端已下发的 `msg_seq`（D10），与 append 天然无写冲突；`meta_json` 的合并以服务端行存在为前提，缺失即拒。
- **并发 run 同一 session**：同一 `session_id` 同时发两个 run 时，seq 由服务端单点分配（事务内 `MAX(seq)+1`），消息按 run 完成顺序落库、可能交错——与今天内存池「history 按完成顺序追加」语义一致，不做串行化。
- **游客 cookie 与池 key 迁移**：`resolve_pool_owner` 从 `ip:` 切 `g:` 后，池 key 里的 owner 段同步变化；旧 `ip:` 池条目随 TTL 驱逐自然消亡，不做数据迁移（内存态本就不持久）。

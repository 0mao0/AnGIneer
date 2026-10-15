# angineer-community

公开测试集页 / 公开 SOP 页的后端：分类树、公开绑定、投稿池与两个上游的只读代理。
设计文档：`docs/design-public-eval-sop-pages.md`（数据流、API 契约、验收清单都在那里）。

## 边界（三句话）

1. **公开什么由 `community_binding` 表决定**，evals-core 与 sop-api 两个上游零改动、本包对其只读。
2. **投稿一律进 `data/platform/community.sqlite`**（status=received），本版只收不审，永不写正式库。
3. **草稿与 gold 不出公开面**：SOP 取数带 `status=published` 且逐条复核；题目走列表投影，八张 gold 列物理不进响应。

## 挂载

不独立起服务。挂在 aichat-api 上（`services/aichat-api/main.py`），前缀 `/api/community`：

```python
from community.service import CommunityService
from community.routes import build_community_router
router = build_community_router(CommunityService(), resolve_principal_with_label)
```

`resolve_principal(request) -> (owner_key, user_id, author_label)`：归属键沿用 chat 侧
`resolve_pool_owner`（`u:` → `k:` → `g:` → `ip:`），游客即 `g:<ag_guest_id>`。

## 数据目录与环境变量

| 变量 | 默认 | 作用 |
|---|---|---|
| `COMMUNITY_DB_PATH` | `data/platform/community.sqlite` | 本库唯一写者路径 |
| `SOP_API_URL` | `http://sop-api:8792` | 只读代理上游（与 aichat 共用） |
| `ANGINEER_SOP_CACHE_TTL` | 300 | SOP 列表 TTL 缓存秒数 |
| `SOP_API_SNAPSHOT_PATH` | `data/platform/sop_published_snapshot.json` | sop-api 不可达时的只读兜底 |
| `COMMUNITY_SHOW_GOLD` | 关 | 仅本地对照：开卷只放行「参考答案」一项，其余 gold 任何开关下都不出 |
| `COMMUNITY_DAILY_LIMIT` | 50 | 单主体滚动 24h 投稿上限（兜底；主防线是 nginx per-IP limit_req） |

## 启动种子（两类语义不同，勿混）

- 分类树节点：每次启动幂等**只补不覆盖**；
- 标题关键词自动绑定：**只跑首次**（`community_meta` marker 置位后永不重跑）。
  新内容要公开 → `scripts/community_bind.py`。

## 运维 CLI

```
python scripts/community_bind.py list [--scope eval|sop] [--unbound]
python scripts/community_bind.py bind <scope> <kind> <ref_id> <node_id>
python scripts/community_bind.py unbind <scope> <kind> <ref_id>
```

# 语料包导入导出：剩余事项

**日期：** 2026-10-21
**当前状态：** v2 导出、CLI 导入、HTTP 导入、admin-web 上传弹框、P4 拆并/改组/删库保护已完成；本文只记录**尚未收口**的事项。
**主计划：** [plan-kb-per-library-package.md](plan-kb-per-library-package.md)

---

## 1. 待办总表

| 优先级 | 事项 | 状态 | 说明 |
|---|---|---|---|
| P0 | P3-4 真实检索探针 | 未做 | 当前测试包只有 1 个 txt，未验证导入库的 FTS/向量检索与 doc_title |
| P0 | P3-4 apply 中途 kill 演练 | 未做 | 杀 docs-api 后重启，确认半成品暂存/冲突提示/清理路径 |
| P0 | P3-3 宿主机 nginx 放行 | 未做 | 容器层已放行；宿主机不改，>200MB 仍 413 |
| P1 | P4-4 CHANGELOG/README/版本 | 待发版 | 版本号需用户确认；不自动 tag/push |
| P2 | 克隆导入（同实例并存） | 可选，未立项 | 需全量 ID 重映射，不是加 `(2)` 后缀 |
| P2 | 测试产物清理 | 未做 | `data/scratch/p3-ui-test`、临时 target、retired 测试行 |
| P2 | 宿主机大文件复测 | 依赖 P3-3 | 上传 >200MB 小/大包各一次 |

---

## 2. P3-4：真实检索探针

**目标：** 导入的库不仅能出现在列表/详情，还能被检索到，`doc_title` 正确。

建议步骤：

1. 用真实小库包（带向量）导入临时 data 根，或导入空环境；
2. 调 `/api/knowledge/search` 或 `POST /v1/retrieve`，指定 `library_id`；
3. 断言：
   - 命中该库文档；
   - `items[].metadata.doc_title` 非空且正确；
   - FTS 与向量各命中一次；
4. 再查 `/api/knowledge/documents/<doc_id>/pdf` 返回 200。

当前测试包 `lib-import-test2.zip` 只有 1 个 txt、0 向量，不能替代这项。

---

## 3. P3-4：apply 中途 kill 演练

**目标：** 导入应用中途 docs-api 挂掉，重启后能识别半成品并给出可执行清理路径。

建议步骤：

1. 用 `lib-import-test2.zip` 或真实小包，在临时 data 根启动 apply；
2. apply 进行到 files/index 阶段时 `Stop-Process` 杀 docs-api；
3. 重启 docs-api；
4. 检查：
   - `data/scratch/imports/<task_id>/` 是否保留；
   - 目标 `knowledge/libraries/<lib>/` 是否有半成品；
   - 再次导入是否被 index/文件冲突拦住；
5. 按提示清理：
   - 暂存包：`DELETE /api/knowledge/imports/<task_id>`（仅进程内任务存在时）；
   - 半成品目录/index：人工确认后删除；
6. 记录实际错误文案；若不够清楚，再补清理 CLI/提示。

**当前已做：** apply 失败会保留暂存并返回 `暂存包 <path>；可 DELETE ...`（路由测试覆盖）。**未做：** 真实 kill/重启演练。

---

## 4. P3-3：宿主机 nginx

容器层已改：[docker/nginx/nginx.conf](../docker/nginx/nginx.conf) 的 `^~ /api/knowledge/imports/`。

宿主机文件：`/etc/nginx/ai-proxy-locations.conf`（不在 git）。

需要加同义 location，代理到**现有 frontend upstream**（不要新起端口）：

```nginx
location ^~ /api/knowledge/imports/ {
    client_max_body_size 0;
    proxy_request_buffering off;
    proxy_read_timeout 600s;
    proxy_send_timeout 600s;
    # proxy_pass 按该文件里现有 frontend 上游填写
}
```

步骤：

1. 先向用户报备（线上入口）；
2. 修改后 `nginx -t`；
3. `systemctl reload nginx`；
4. 上传小包（<10MB）与 >200MB 包各一次，确认不再 413；
5. 记录：小包成功、大包成功、失败时的具体状态码。

**未做：** 宿主机改动与 >200MB 复测。

---

## 5. P4-4：发版收尾

- CHANGELOG/README 摘要**留到发版时**写，按 AGENTS.md 契约；
- 版本号先报用户确认，不自行定号；
- `pnpm release` 前不手改 README/package.json 版本；
- 不自动 tag、不自动 push。

发版前建议至少完成：P3-3 宿主机放行、P3-4 检索探针、真实小包/大包各一次导入。

---

## 6. 可选：同实例克隆导入（未立项）

需求：旧库保留，新库在同一后台并存。

不是改 `library_id` 后缀即可：

- 节点 `nodes.id`、`doc_id`、`chunk_id`、图谱 `entity_id/relation_id` 都是全局主键；
- 文件路径、meta、graph、qdrant payload/collection 都要跟着重映射；
- 需要新命令/选项（如 `--as-library-id`）+ 小包测试 + default 包验证。

**建议：** 除非“同一后台并排两份”是硬需求，否则不做；迁移/恢复用空 data 根/另一环境即可。

---

## 7. 清理与收尾

- `data/scratch/p3-ui-test/lib-import-test2.zip`：有效测试包，可留可删；
- `data/scratch/p3-ui-target*`、`p2-5`、`p2-cli-target`：临时导入根，确认后可删；
- `lib-import-test` / `lib-import-test2` 的 `retired` 审计行：列表不显示，可留审计；确认不再恢复可手工清；
- docs-api 是 detached 进程（不是受管 job），日志在 `data/logs/docs-api-import.log`；
- 不要提交 `data/`、`.dsh-figures/`、Harvey/时间维度那条线的未提交改动。

---

## 8. 已知边界（当前版本）

- 导入包内 `files/` 根必须与目标组 `libraries_dir` 一致（knowledge 包用 knowledge 组，evals 包用 evals 组）；
- 不支持 v1 目录/tar 包；
- 不支持 reembed，模型不一致直接阻断；
- 普通“新建库”仍走组共享桶；只有 v2 包导入走独立桶；
- 导入不自动合并/覆盖同名库；同 `library_id` 的 retired 行可被 restore 替换；
- 应用阶段不可取消，失败保留暂存；
- 上传支持 multipart，不支持断点续传。

---

## 9. 相关提交

- P2-3 CLI：`31e7a30a`
- P3-1 路由：`4ccb8d01`
- P3-2 UI：`37d8311a` / `c25cdc29`
- P3-3 容器 nginx：`d68f92c2`
- P4-0 删库：`00817fdf` / `21b90628`
- P4-1/P4-2/P4-3：`b4203b04` / `475376ab` / `2508774a`
- P4-4 文档：`ac1535f4`
- 台账/删库补丁：`98959483` / `b858e2c3`
- 删库 Windows 锁/重试：`34183442`
- retired 同 id 恢复：`d02d8c04`
- P3-4 断点测试：`66ff9ada`

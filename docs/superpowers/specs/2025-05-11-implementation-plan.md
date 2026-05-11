# 实施计划：Code Fix + SOP 经验库页面

> 日期：2025-05-11
> 基于：code-fix-plan.md + SOP 经验库页面设计规格

---

## 阶段总览

| 阶段 | 内容 | 预计子任务数 |
|------|------|-------------|
| Phase 1 | Code Fix（低风险，无依赖） | 4 |
| Phase 2 | Code Fix（中风险，顺序执行） | 3 |
| Phase 3 | Code Fix（高风险，模块解耦） | 1 |
| Phase 4 | SOP 后端 API | 3 |
| Phase 5 | SOP 前端基础设施 | 4 |
| Phase 6 | SOP 前端核心功能 | 5 |
| Phase 7 | SOP 前端高级功能 | 3 |

---

## Phase 1：Code Fix — 低风险，无依赖

### 1.1 [3.2] LLM 客户端 base_url 处理逻辑重复

**文件**: `services/ai-inference/src/ai_inference/llm_client.py`

**改动**:
1. 在 `LLMClient` 类中新增静态方法 `_normalize_base_url(base_url: str) -> str`
2. `_call_openai` (L260-L262): 将 `if base_url.endswith(...)` 替换为 `base_url = self._normalize_base_url(config.base_url)`
3. `_call_openai_stream` (L306-L308): 同上

**验证**: `pnpm harness` 通过

---

### 1.2 [3.4] 异常处理过于宽泛

**文件**:
- `services/angineer-core/src/angineer_core/dispatcher.py` (L108-L110, L172-L175)
- `services/evals-core/src/evals_core/runner/answer_eval.py` (L131-L138)
- `services/evals-core/src/evals_core/runner/suite_runner.py` (L230-L233)
- `services/api-server/main.py` (L49-L63)

**改动**:
1. 新建 `services/angineer-core/src/angineer_core/base_utils.py`，定义 `FATAL_EXCEPTIONS` 和 `is_fatal_exception()`
2. 各处 `except Exception as e:` 后增加 `if is_fatal_exception(e): raise`
3. `main.py` 全局异常处理器中增加 `if is_fatal_exception(exc): raise`

**验证**: `Ctrl+C` 可正常终止程序；正常异常仍被捕获

---

### 1.3 [4.2] AIChat 组件直接使用 fetch

**文件**:
- `packages/ui-kit/src/components/common/AIChat.vue` (L111-L124)
- `packages/ui-kit/src/composables/useAIChat.ts` (L291)
- `apps/admin-console/src/views/EvalManage.vue` (L544)

**改动**:
1. 新建 `packages/ui-kit/src/api/client.ts`，封装 `apiClient.get/post` 和领域 API（`llmApi`、`queryApi`）
2. `AIChat.vue` 的 `fetchModels` 改用 `llmApi.getConfigs()`
3. `useAIChat.ts` 的 `fetch('/api/query', ...)` 改用 `queryApi.query()`
4. `EvalManage.vue` 中的直接 `fetch` 调用改用 `apiClient`

**验证**: AI 对话功能正常；无直接 `fetch('/api/...')` 调用

---

### 1.4 [2.1] 会话池并发安全问题

**文件**: `services/api-server/main.py` (L127-L148)

**改动**:
1. 新增 `_session_lock = threading.Lock()`
2. `_get_or_create_session` 整体包裹 `with _session_lock:`
3. `_evict_expired_sessions` 整体包裹 `with _session_lock:`

**验证**: 并发请求不会导致会话池数据竞争

---

## Phase 2：Code Fix — 中风险，顺序执行

### 2.1 [1.2] 全局单例 → 懒加载

**文件**:
- `services/ai-inference/src/ai_inference/llm_client.py` (L527-L534)
- `services/angineer-core/src/angineer_core/classifier.py` (L10-L11)
- `services/angineer-core/src/angineer_core/dispatcher.py` (L30)
- `services/docs-core/src/docs_core/knowledge_service.py` (L546)
- 所有引用 `knowledge_service` 的文件

**改动**:
1. `llm_client.py` 底部：删除 `llm_client = get_llm_client()` 模块级初始化，保留 `get_llm_client()` 懒加载
2. `classifier.py` L10: `from ai_inference.llm_client import llm_client` → `from ai_inference.llm_client import get_llm_client`；使用时 `get_llm_client()`
3. `dispatcher.py` L30: `from ai_inference.llm_client import llm_client as default_llm_client` → `from ai_inference.llm_client import get_llm_client`；`__init__` 中 `self._llm_client = llm_client or get_llm_client()`
4. `knowledge_service.py` L546: `knowledge_service = KnowledgeService()` → 懒加载函数 `get_knowledge_service()`
5. 全局搜索替换所有 `from docs_core.knowledge_service import knowledge_service` → `from docs_core.knowledge_service import get_knowledge_service`

**验证**: 无模块级立即初始化的单例；`pnpm harness` 通过

---

### 2.2 [2.3] L0 闲聊误判修复

**文件**: `services/angineer-core/src/angineer_core/classifier.py` (L117-L130)

**改动**:
1. 拆分 `L0_KEYWORDS` 为 `L0_PURE_CHAT_KEYWORDS`（你好/嗨/hello/再见/谢谢等）和 `L0_AMBIGUOUS_KEYWORDS`（帮我/怎么用/能做什么/你是谁等）
2. 新增 `_has_substantive_content(query)` 函数：检测规范编号、条款编号、参数赋值、多个数值、L1-L4 关键词、长句(>15字)
3. 修改 `_rule_based_classify` L0 检测逻辑：纯闲聊关键词 + 无实质性内容 → L0；歧义关键词 + 有实质性内容 → 继续后续分类

**验证**: "你好，请问 GB 50010 中混凝土强度如何确定？" 不被误判为 L0；纯 "你好" 仍为 L0

---

### 2.3 [1.2 续] base_config 全局单例

**文件**: `services/angineer-core/src/angineer_core/base_config.py` (L117-L123)

**改动**:
1. `_config` 全局变量改为 `None` 初始值（如果还不是的话）
2. 确保 `get_config()` 是懒加载模式（已是，确认即可）
3. 确认无模块级 `_config = load_config_from_env()` 立即初始化

**验证**: `get_config()` 懒加载正常

---

## Phase 3：Code Fix — 高风险，模块解耦

### 3.1 [1.1] 模块解耦 Protocol + DI

**文件**:
- 新建 `services/angineer-core/src/angineer_core/contracts.py`
- `services/angineer-core/src/angineer_core/dispatcher.py`
- `services/api-server/main.py`
- `services/evals-core/src/evals_core/runner/_query_helper.py`

**改动**:
1. 新建 `contracts.py`，定义 `KnowledgeProvider(Protocol)`、`SopProvider(Protocol)`、`LLMProvider(Protocol)`
2. `Dispatcher.__init__` 新增 `knowledge_provider`、`sop_provider` 参数，删除内部 `from docs_core...` import
3. `Dispatcher.dispatch` 中 `from docs_core.knowledge_service import knowledge_service` → `self._knowledge_provider`
4. `main.py` 启动组装：创建 Dispatcher 时注入依赖，删除 `sys.path.append`
5. `_query_helper.py`：创建 Dispatcher 时注入依赖

**验证**: `angineer-core` 模块内无 `from docs_core` / `from sop_core` 直接 import；`main.py` 中无 `sys.path.append`；`pnpm harness` 通过

---

## Phase 4：SOP 后端 API

### 4.1 新建 SOP 路由模块

**文件**: 新建 `services/api-server/sop_routes.py`

**改动**:
1. 创建 `sop_router = APIRouter(prefix="/api/sops")`
2. 实现 `GET /` — 列表，扫描 `data/sops/json/*.json`，返回元数据列表
3. 实现 `GET /{sop_id}` — 读取单个 JSON 文件，返回完整内容
4. 实现 `PUT /{sop_id}` — 接收前端编辑后的 JSON，写回文件
5. 实现 `POST /` — 创建新 SOP（生成 JSON 文件）
6. 实现 `DELETE /{sop_id}` — 删除 JSON 文件
7. 实现 `GET /folders` — 读取文件夹结构（从 `data/sops/folders.json`，不存在则返回空）
8. 实现 `POST /folders` — 创建文件夹（写入 `folders.json`）

**验证**: 通过 curl/Postman 测试所有端点

---

### 4.2 注册 SOP 路由到主应用

**文件**: `services/api-server/main.py`

**改动**:
1. `from sop_routes import sop_router`
2. `app.include_router(sop_router, prefix="/api/sops", tags=["SOPs"])`
3. 删除旧的 `@app.get("/sops")` 和 `@app.post("/sops")` 端点（已被新路由替代）

**验证**: 前端可通过 `/api/sops` 访问 SOP 数据

---

### 4.3 适配 SopLoader 读取 JSON 目录

**文件**: `services/sop-core/src/sop_core/sop_loader.py`

**改动**:
1. `_load_from_index` 方法增加直接从 JSON 目录加载的逻辑（已有部分实现，需完善）
2. 确保 `load_all()` 能正确读取 `data/sops/json/` 下的文件
3. `analyze_sop` 保持现有缓存逻辑不变

**验证**: `sop_loader.load_all()` 返回正确的 SOP 列表

---

## Phase 5：SOP 前端基础设施

### 5.1 安装 Vue Flow 依赖

**命令**:
```bash
cd packages/sop-ui && pnpm add @vue-flow/core @vue-flow/controls @vue-flow/background @vue-flow/minimap
cd apps/admin-console && pnpm add @vue-flow/core @vue-flow/controls @vue-flow/background @vue-flow/minimap
```

**验证**: `pnpm install` 无报错

---

### 5.2 扩展 SOP 类型定义

**文件**: `packages/sop-ui/src/types/sop.ts`

**改动**:
1. 新增 `SopStep` 接口（id, name, description, tool, inputs, outputs, notes, analysis_status）
2. 新增 `SopData` 接口（id, name_zh, name_en, description, folder_id, steps, blackboard）
3. 新增 `SopFolder` 接口（folder_id, title, parent_folder_id, children）
4. 新增 `VueFlowNode` / `VueFlowEdge` 类型别名

**验证**: TypeScript 编译无报错

---

### 5.3 新建 SOP API 封装

**文件**: 新建 `packages/sop-ui/src/composables/useSopApi.ts`

**改动**:
1. 使用 `@/api/client.ts` 的 `apiClient`（Phase 1.3 已创建）
2. 封装 `sopApi.listSops()`、`sopApi.getSop(id)`、`sopApi.saveSop(id, data)`、`sopApi.createSop(data)`、`sopApi.deleteSop(id)`
3. 封装 `sopApi.getFolders()`、`sopApi.createFolder(data)`

**验证**: API 调用返回正确数据

---

### 5.4 扩展 useSopTree composable

**文件**: `packages/sop-ui/src/composables/useSopTree.ts`

**改动**:
1. 删除硬编码的 `createDefaultSopTree()`
2. 新增 `fetchTreeFromApi()` — 调用 `sopApi.listSops()` + `sopApi.getFolders()` 构建树
3. 新增 `fetchSopDetail(sopId)` — 调用 `sopApi.getSop(id)` 获取完整 SOP 数据
4. 新增 `createFolder(parentId, name)` — 调用 API 创建文件夹
5. 新增 `deleteSop(sopId)` — 调用 API 删除

**验证**: 左侧树能从后端加载真实 SOP 数据

---

## Phase 6：SOP 前端核心功能

### 6.1 新建 SOPFlowCanvas 组件

**文件**: 新建 `packages/sop-ui/src/components/SOPFlowCanvas.vue`

**改动**:
1. 使用 `<VueFlow>` 组件，注册自定义节点类型 `sop-step` 和自定义边类型 `sop-edge`
2. 引入 `<Controls>`、`<Background>`、`<MiniMap>` 附加组件
3. Props: `sopData: SopData | null`
4. Emits: `step-select`, `step-dblclick`, `save`, `dirty-change`
5. 工具栏：适应画布、放大/缩小、自动布局、添加步骤、保存按钮
6. 右键菜单：添加步骤、删除步骤、在后方插入
7. 导入 Vue Flow 样式 + 主题 CSS 变量覆盖

**验证**: 画布能渲染 SOP 步骤流程图

---

### 6.2 新建 SOPStepNode 自定义节点

**文件**: 新建 `packages/sop-ui/src/components/SOPStepNode.vue`

**改动**:
1. 卡片式布局：步骤序号（圆形标记）+ 步骤名称 + 工具图标 + 描述截断
2. 使用 `<Handle>` 组件定义顶部输入和底部输出连接点
3. 样式使用 CSS 变量：`--panel-bg`、`--border-color`、`--text-primary`、`--primary-color`
4. 选中态/悬停态样式
5. 工具类型图标映射：calculator→CalculatorOutlined, table_lookup→TableOutlined, auto→ThunderboltOutlined, 其他→ToolOutlined

**验证**: 节点渲染正确，连接点可拖拽连线

---

### 6.3 新建 SOPStepEdge 自定义边

**文件**: 新建 `packages/sop-ui/src/components/SOPStepEdge.vue`

**改动**:
1. 使用 `<BaseEdge>` + `<getBezierPath>` 绘制贝塞尔曲线
2. 带箭头
3. 选中时高亮（`--primary-color`）
4. 可选显示数据流标签

**验证**: 边渲染正确，连接节点

---

### 6.4 新建 useSopFlow composable

**文件**: 新建 `packages/sop-ui/src/composables/useSopFlow.ts`

**改动**:
1. `loadFromSopData(data: SopData)` — 将 SOP JSON 转换为 Vue Flow Nodes/Edges
   - 每个 step → 一个 Node（type='sop-step', position 由 dagre 自动计算）
   - 相邻 step → 一条 Edge
2. `exportToSopData()` — 将 Vue Flow Nodes/Edges 转换回 SOP JSON
3. `addStep(afterStepId?)` — 添加新步骤节点
4. `removeStep(stepId)` — 删除步骤节点及相关边
5. `autoLayout()` — 使用 dagre 自动布局
6. `isDirty` — 脏标记
7. `selectedStepId` — 当前选中步骤

**验证**: JSON ↔ Vue Flow 双向转换正确

---

### 6.5 新建 ExperienceManage 页面

**文件**: 修改 `apps/admin-console/src/views/ExperienceManage.vue`（替换 PlaceholderPage）

**改动**:
1. 三栏布局：`<SplitPanes>` + `<Panel>`
2. 左侧：`<SOPTree>` + `useSopTree`
3. 中间：`<SOPFlowCanvas>` + `useSopFlow`
4. 右侧：`<a-tabs>` 包含属性面板和 AI 对话
5. 路由更新：`/experience` → `ExperienceManage.vue`
6. 状态编排：树选择 → 加载流程图 → 节点双击 → 属性面板

**验证**: 页面三栏布局正常，基本交互可用

---

## Phase 7：SOP 前端高级功能

### 7.1 新建 SOPPropertyPanel 属性面板

**文件**: 新建 `packages/sop-ui/src/components/SOPPropertyPanel.vue`

**改动**:
1. 表单字段：id（只读）、name、description、tool（下拉）、inputs（键值对）、outputs（键值对）、notes
2. `useSopProperty` composable 管理当前选中步骤的编辑状态
3. 编辑后同步回 `useSopFlow`，标记 `isDirty`
4. inputs/notes 字段集成 SOPReferenceInput

**验证**: 属性面板展示和编辑正常

---

### 7.2 新建 SOPReferenceInput @引用组件

**文件**: 新建 `packages/sop-ui/src/components/SOPReferenceInput.vue`

**改动**:
1. 输入框 + `@` 触发下拉搜索
2. 搜索知识库文档列表（`knowledgeApi.getNodes`）
3. 选中文档后加载 block 列表（`knowledgeApi.getStructuredIndex`）
4. 选中 block 后插入 `@{doc_id:block_id:display_name}` 标记
5. 已有引用显示为可删除 Tag

**验证**: @引用输入和显示正常

---

### 7.3 右侧 AI 对话 Tab

**文件**: `apps/admin-console/src/views/ExperienceManage.vue`

**改动**:
1. 右侧第二个 Tab 使用 `<AIChat>` 组件
2. `scene="sop"`
3. `sessionId` 绑定当前 SOP ID
4. 预留后续 SOP 执行对话扩展

**验证**: AI 对话在 SOP 页面正常工作

---

## 验收清单

### Code Fix 验收
- [ ] `llm_client.py` 无重复 base_url 处理逻辑
- [ ] 致命异常（KeyboardInterrupt）可正常终止程序
- [ ] 无直接 `fetch('/api/...')` 调用
- [ ] 会话池操作在锁保护下
- [ ] 无模块级立即初始化的单例
- [ ] "你好，请问 GB 50010 中混凝土强度如何确定？" 不被误判为 L0
- [ ] `angineer-core` 模块内无 `from docs_core` / `from sop_core` 直接 import
- [ ] `main.py` 中无 `sys.path.append`
- [ ] `pnpm harness` 通过

### SOP 经验库验收
- [ ] 左侧树加载 data/sops/json 目录下的 JSON 文件
- [ ] 选中 SOP 文件后中间画布渲染流程图
- [ ] 双击节点右侧属性面板展示详情
- [ ] 属性面板可编辑步骤属性
- [ ] 手动保存后 JSON 文件更新
- [ ] 右键菜单支持增删步骤
- [ ] inputs/notes 字段支持 @引用
- [ ] AI 对话 Tab 正常工作
- [ ] 明暗主题切换正常
- [ ] `pnpm lint` 通过
- [ ] `pnpm build` 通过

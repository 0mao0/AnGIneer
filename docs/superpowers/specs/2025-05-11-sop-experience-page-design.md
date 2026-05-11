# SOP 经验库页面设计规格

> 日期：2025-05-11
> 状态：待审批

---

## 1. 目标

在 `http://localhost:3002/experience` 实现 SOP 经验库管理页面，提供三栏式布局：
- 左侧：基于 SmartTree 的 SOP 文件树
- 中间：Vue Flow 流程图可视化 SOP 步骤
- 右侧：属性面板 + AI 对话双 Tab

支持 SOP 的增删查改、步骤节点的可视化编辑、知识库 @引用。

## 2. 技术选型

| 决策项 | 选择 | 理由 |
|--------|------|------|
| 流程图库 | @vue-flow/core + 附加组件 | Vue 3 原生、社区活跃、自定义能力强 |
| 数据存储 | 文件系统 JSON | 与现有 SopLoader JSON 缓存机制一致 |
| 保存策略 | 手动保存 | 安全可控，支持撤回 |
| @引用范围 | 仅 inputs/notes 字段 | 范围明确，实现简单 |

## 3. 架构

### 3.1 页面结构

```
┌──────────────────────────────────────────────────────────────────┐
│  AppHeader (已有，导航 "经验库")                                    │
├───────────────┬─────────────────────────┬────────────────────────┤
│  左侧 SOPTree  │  中间 Vue Flow 流程图     │  右侧双 Tab 面板        │
│  (SmartTree)   │  (自定义节点/边/交互)      │  [属性] [AI对话]        │
│                │                         │                        │
│  📁 设计流程    │  ┌──────┐  ┌──────┐    │  节点ID: step_1        │
│   ├ 航道设计    │  │step_1│─▶│step_2│    │  名称: 核心参数解析      │
│   └ 码头选址    │  └──────┘  └──────┘    │  工具: table_lookup     │
│  📁 能力测算    │      │                  │  输入: {...}           │
│   └ 泊位通过    │      ▼                  │  输出: {...}           │
│                │  ┌──────┐              │  备注: ...             │
│                │  │step_3│              │                        │
│                │  └──────┘              │                        │
├───────────────┴─────────────────────────┴────────────────────────┤
```

### 3.2 组件拆分

```
apps/admin-console/src/views/
  ExperienceManage.vue              ← 页面主组件（三栏布局 + 状态编排）

packages/sop-ui/src/
  components/
    SOPTree.vue                     ← 已有，左侧树（需微调）
    SOPFlowCanvas.vue               ← 新增，中间流程图画布
    SOPStepNode.vue                 ← 新增，Vue Flow 自定义步骤节点
    SOPStepEdge.vue                 ← 新增，Vue Flow 自定义边
    SOPPropertyPanel.vue            ← 新增，右侧属性面板
    SOPReferenceInput.vue           ← 新增，@引用输入组件
  composables/
    useSopTree.ts                   ← 已有，需扩展（从 API 加载真实数据）
    useSopFlow.ts                   ← 新增，流程图状态管理
    useSopProperty.ts               ← 新增，属性面板状态管理
    useSopApi.ts                    ← 新增，SOP CRUD API 封装
  types/
    sop.ts                          ← 已有，需扩展 Step 详细类型
```

### 3.3 数据流

```
用户点击左侧树节点
  → useSopApi.loadSopDetail(sopId)
  → useSopFlow.loadFromSopData(data)    // JSON → Vue Flow Nodes/Edges
  → 中间画布渲染流程图

用户双击流程图节点
  → useSopProperty.selectStep(stepId)   // 设置当前选中步骤
  → 右侧属性面板展示详情
  → 用户编辑属性 → useSopProperty.updateField()
  → 同步回 useSopFlow 的节点数据

用户点击保存
  → useSopFlow.exportToSopData()        // Vue Flow → JSON
  → useSopApi.saveSop(sopId, data)      // PUT /api/sops/{sopId}
```

## 4. 左侧 SOPTree

### 4.1 功能

- 基于 SmartTree，文件类型为 `.json`
- 自动加载 `data/sops/json` 目录下的所有 JSON 文件
- 支持新建文件夹（前端虚拟文件夹，保存时记录到 SOP 元数据）
- 选中 SOP 文件 → 加载流程图到中间画布
- 支持搜索、重命名、删除

### 4.2 树节点类型

- 文件夹节点：`isFolder: true`，可包含子文件夹和文件
- SOP 文件节点：`isFolder: false`，叶子节点，图标使用 `ApiOutlined`

### 4.3 API

```
GET  /api/sops/folders              ← 获取文件夹结构
POST /api/sops/folders              ← 创建文件夹
```

## 5. 中间 Vue Flow 流程图

### 5.1 自定义节点 SOPStepNode

每个步骤渲染为一个卡片节点，包含：
- 步骤序号（左上角圆形标记）
- 步骤名称（主标题）
- 工具类型图标（右上角，根据 tool 字段显示不同图标）
- 简要描述（副标题，截断显示）

节点样式：
- 选中态：高亮边框（`--primary-color`）
- 悬停态：轻微阴影
- 背景色/文字色跟随 `useTheme()` 的 CSS 变量

### 5.2 自定义边 SOPStepEdge

- 带箭头的有向边
- 默认使用贝塞尔曲线
- 选中时高亮
- 可选显示数据流标签（从 source step 的 outputs → target step 的 inputs 的映射关系）

### 5.3 交互

| 操作 | 行为 |
|------|------|
| 双击节点 | 右侧属性面板展示该步骤详情 |
| 单击节点 | 选中节点（高亮边框），属性面板同步 |
| 右键节点 | 上下文菜单：编辑、删除、在后方插入步骤 |
| 右键画布空白 | 上下文菜单：添加步骤 |
| 拖拽节点 | 调整位置 |
| 拖拽边 | 重新连接步骤顺序 |
| 工具栏 | 自动布局、缩放适应、撤销/重做 |

### 5.4 自动布局

使用 `dagre` 算法进行自上而下的自动布局：
- 步骤按顺序从上到下排列
- 分支步骤左右展开
- 保存时仅保存步骤数据，不保存位置信息（下次打开自动布局）

### 5.5 工具栏

画布顶部工具栏：
- 适应画布（Fit View）
- 放大/缩小
- 自动布局
- 添加步骤
- 保存（主按钮，带脏标记）

## 6. 右侧双 Tab 面板

### 6.1 Tab 1：属性面板

展示当前选中步骤的完整属性，支持编辑：

| 字段 | 类型 | 说明 |
|------|------|------|
| id | 文本（只读） | 步骤唯一标识 |
| name | 文本 | 步骤名称 |
| description | 多行文本 | 步骤描述 |
| tool | 下拉选择 | 工具类型（calculator/table_lookup/auto/echo 等） |
| inputs | 键值对编辑器 | 输入参数，值支持 @引用 |
| outputs | 键值对编辑器 | 输出参数 |
| notes | 多行文本 | 备注，支持 @引用 |

### 6.2 Tab 2：AI 对话

- 复用 AIChat 组件
- `scene="sop"`
- `sessionId` 绑定当前 SOP ID
- 预留后续扩展（如 SOP 执行对话、步骤建议等）

### 6.3 @引用输入组件 SOPReferenceInput

在 inputs 和 notes 字段中支持 `@xxx` 语法：
- 输入 `@` 时弹出知识库 block 搜索下拉
- 搜索数据源：调用 `GET /api/knowledge/nodes` 获取知识库文档列表，再调用 `GET /api/knowledge/structured/{doc_id}` 获取 block 列表
- 选中后插入引用标记 `@{doc_id:block_id:display_name}`
- 显示为可删除的标签（Tag）
- 后续执行时由后端解析引用并拉取实际内容

## 7. 后端 API 扩展

### 7.1 新增端点

```
GET  /api/sops                      ← 列表（适配 JSON 模式，返回元数据）
GET  /api/sops/{sop_id}             ← 获取单个 SOP JSON 详情
PUT  /api/sops/{sop_id}             ← 更新 SOP JSON（手动保存触发）
POST /api/sops                      ← 创建新 SOP
DELETE /api/sops/{sop_id}           ← 删除（已有）
GET  /api/sops/folders              ← 获取文件夹结构
POST /api/sops/folders              ← 创建文件夹
```

### 7.2 数据格式

GET /api/sops/{sop_id} 返回：
```json
{
  "id": "挖槽宽度",
  "name_zh": "挖槽宽度",
  "name_en": "trench_width",
  "description": "计算航道挖槽的底宽",
  "folder_id": "folder-design",
  "steps": [
    {
      "id": "step_1",
      "name": "核心参数解析与继承",
      "description": "解析并继承通航宽度...",
      "tool": "auto",
      "inputs": { "W": "通航宽度 (m)" },
      "outputs": { "W": "通航宽度 (m)" },
      "notes": "若 W 或 Slope 缺失...",
      "analysis_status": "analyzed"
    }
  ],
  "blackboard": {
    "required": ["W", "Slope"],
    "outputs": ["W_dredge"]
  }
}
```

PUT /api/sops/{sop_id} 请求体同上格式，后端写入 `data/sops/json/{sop_id}.json`。

## 8. 依赖安装

```bash
pnpm add @vue-flow/core @vue-flow/controls @vue-flow/background @vue-flow/minimap
```

安装到 `packages/sop-ui` 和 `apps/admin-console`。

## 9. 主题适配

所有新增组件必须使用 `useTheme()` 提供的 CSS 变量：
- 节点背景：`--panel-bg`
- 节点边框：`--border-color`
- 文字颜色：`--text-primary` / `--text-secondary`
- 选中高亮：`--primary-color`
- 画布背景：`--bg-secondary`
- 工具栏背景：`--panel-header-bg`

Vue Flow 的 CSS 变量覆盖：
```css
:root {
  --vf-node-bg: var(--panel-bg);
  --vf-node-text: var(--text-primary);
  --vf-node-border: var(--border-color);
  --vf-connection-path: var(--text-secondary);
  --vf-handle: var(--primary-color);
}
```

## 10. 前置条件

SOP 模块开发前需完成 code-fix-plan 中的以下修复：
1. **1.2 全局单例 → 懒加载**（sop_loader 也是全局单例）
2. **4.2 AIChat fetch 封装**（SOP 页面复用 AIChat）
3. **1.1 模块解耦 Protocol + DI**（新增 SOP API 时避免继续恶化 sys.path.append）

## 11. 验收标准

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

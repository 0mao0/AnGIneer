# AGENTS.md

## 1. 目标定位
本文件定义本仓库 Coding Agent 的执行 Harness。
它应当保持简短、可执行、可验证。

## 2. 工作模型（Harness Engineering）
对所有非琐碎任务，Agent 必须按以下闭环执行：
1. 研究：定位相关架构、模块和契约。
2. 规划：把目标深度优先拆为可验证子任务。
3. 执行：一次只做一个边界清晰的改动。
4. 验证：运行必要检查并确认行为结果。
5. 交付：汇总改动、证据与剩余风险。

应识别缺失能力，并把修复沉淀为可复用约束、测试或规则。

## 3. 真相源地图
先读总览，再按模块下钻：
- 项目总览：[README.md](file:///d:/AI/AnGIneer/README.md)
- 前端技术细节：[docs/apps-techniques.md](file:///d:/AI/AnGIneer/docs/apps-techniques.md)
- 后端技术细节：[docs/services-techniques.md](file:///d:/AI/AnGIneer/docs/services-techniques.md)
- 根脚本与质量门禁：[package.json](file:///d:/AI/AnGIneer/package.json)
出现冲突时，以“离改动最近的模块文档”为准。

## 4. 架构护栏
- Monorepo 边界：
  - 前端应用：`apps/web-console`、`apps/admin-console`
  - API 网关：`apps/api-server`
  - 共享 UI 包：`packages/*`
  - 核心服务：`services/*`
- 新增能力前优先复用共享组件：
  - AIChat：`packages/ui-kit/src/components/common/AIChat.vue`
  - SOPTree：`packages/docs-ui/src/components/common/widgets/SOPTree.vue`
  - SmartTree：`packages/ui-kit/src/components/common/SmartTree.vue`
- 应用级可复用组件（同应用内多页面共用）：
  - FolderModal：`apps/admin-console/src/views/components/FolderModal.vue`（新建/重命名文件夹弹窗，KnowledgeManage 与 EvalManage 共用）
- `web-console` 与 `admin-console` 默认保持行为一致，除非需求明确区分。
- 优先扩展既有协议和适配器，避免平行实现。

## 5. 执行契约

### 5.1 设计原则
- 编码前先思考:不确定时要询问，不要默默选择一种解释就直接开始
- 简约至上:代码最简化，任何过度设计都一目了然
- 精确编辑:只修改必要的部分，不要顺便修复旁边的代码
- 目标驱动:在开始前将模糊的指令转化为可验证的目标

### 5.2 编码前检查
- 检查相邻文件的风格、导入与实现模式。
- **同应用 UI 模式复用检查**：实现弹窗、表单、操作流程等 UI 交互前，必须先搜索同应用（`apps/admin-console` 或 `apps/web-console`）内是否已有相同或相似的实现。若已有声明式组件覆盖该功能（如 `FolderModal.vue` 覆盖文件夹新建/重命名），必须复用，不得用 `modal.confirm`/`h()` 等命令式 API 重新实现。简单确认弹窗（如删除确认）使用 `modal.confirm` 是合理的。
- 引入新依赖前先确认仓库已使用或确有必要。
- 在动手前明确验收标准与验证方式。

### 5.3 编码中
- 不把无关重构混入功能或缺陷修复。
- 非迁移任务不随意破坏已有 API 契约。
- Vite 配置以 `vite.config.ts` 为唯一真相源，不保留同名 `vite.config.js` 副本。
- 禁止写入密钥、凭据和环境敏感信息。
- 对于 Vue 3 项目，涉及第三方库（如 pdf.js）的对象时，若其内部包含原生私有字段（以 # 开头），必须使用 `shallowRef` 而非 `ref`，以避免 Proxy 代理导致的私有字段访问错误。`ResizeObserver` 等浏览器原生对象同理。
- PDF 渲染约束（详细实践见 `docs/apps-techniques.md`）：
  - 渲染前必须填充白色背景，设置 Canvas 尺寸前必须校验是否变化，防止闪烁。
  - 必须使用 `ResizeObserver` 监听容器尺寸变化以实现自适应缩放。

- 主题与样式开发规范（Theme & Style Guardrails）：
  - **唯一真相源**：主题状态统一通过 `@angineer/ui-kit` 的 `useTheme()` 获取，CSS 变量统一由 `@angineer/ui-kit/stores/theme.ts` 定义。禁止私自使用 `window.matchMedia` 获取系统主题，禁止使用未在 `theme.ts` 中定义的 CSS 变量。
  - **禁止局部硬编码**：禁止在组件 `<style>` 中写死暗黑颜色覆盖（如 `.dark-mode { background: #0f141d; }`），必须使用 `theme.ts` 定义的全局 CSS 变量。
  - **弹窗样式隔离**：挂载到 `body` 的弹窗组件，必须通过 `wrapClassName` 传入主题类名进行样式隔离，严禁移除 `<style scoped>` 导致样式污染全局。

- 组件复用与封装规范（Component Reuse Guardrails）：
  - **禁止跨包复制组件**：同一组件只允许存在一份源码。`packages/ui-kit` 是共享 UI 的唯一真相源。`packages/docs-ui`、`packages/evals-ui` 等领域包必须通过 `import { SmartTree } from '@angineer/ui-kit'` 引用，不得创建本地副本。
  - **禁止同应用内重复实现 UI 模式**：同一应用内，若已有声明式组件覆盖某功能（如 `FolderModal.vue` 覆盖文件夹新建/重命名），必须复用该组件，不得用 `modal.confirm`/`h()` 等命令式 API 重新实现。简单确认弹窗（如删除确认）使用 `modal.confirm` 是合理的。若已有组件不满足需求，应扩展已有组件而非另起炉灶。
  - **SmartTree 使用模式**：所有基于 SmartTree 的领域树（KnowledgeTree、SOPTree、EvalDatasetTree 等）必须遵循语义封装模式——创建领域语义组件，透传 SmartTree 的 props/slots/events，暴露领域类型（如 `KnowledgeTreeNode`、`EvalTreeNode`），通过 `ref` 暴露 `expandedKeys`/`selectedKeys` 等方法。禁止直接在页面级组件中使用 SmartTree。
  - **树节点操作按钮规范**：SmartTree 的 `#actions` 插槽中，叶子节点默认操作为"重命名、查看、删除"三个按钮；文件夹节点默认操作为"重命名、添加子文件夹、[可选]添加文件、删除"。如需增减按钮，必须在语义封装层中明确声明并注释原因。

### 5.4 编码后
- 运行与改动范围匹配的质量检查。
- 涉及架构调整时，同步更新 `docs/services-techniques.md`、`docs/apps-techniques.md` 与 `README.md`。
- 涉及架构边界、模块依赖、主链路或端口契约调整时，必须同步更新 `docs/architecture-map.yaml` 并执行 `pnpm docs:arch-check`。
- 默认在仓库根目录执行：
  - `pnpm run lint`
  - `pnpm docs:arch-check`（影响架构文档、模块边界、主链路时）
  - `pnpm harness`（影响后端/核心逻辑时）
  - `pnpm harness:workflow`（影响端到端 SOP 流程时）
  - `pnpm harness:tooling`（影响工具注册/调用时）
- 检查失败要么修复，要么附带阻塞证据。

## 6. 质量门槛
Definition of Done：
- 行为满足用户目标。
- 关键接口与模块契约保持一致。
- 相关自动化检查通过。
- 交付说明包含：
  - 改了什么
  - 为什么改
  - 如何验证
  - 还存在哪些风险

## 7. Harness 演进策略
- 优先改已有文件，不轻易新增文件。
- 优先做小步、可审阅、可回退的改动。
- 同类错误重复出现时，优先强化 Harness：
  - 增加结构化约束
  - 增加针对性测试
  - 增加明确文档索引
把重复错误视为“基础设施缺失”，而非“模型偶发失误”。

## 8. 技术栈与运行事实
- 操作系统基线：Windows
- 前端：Vue 3 + TypeScript + Vite + Pinia + Vue Router + Ant Design Vue + Less
- 后端：`services/*` 下 Python 服务
- 包管理器：`pnpm`
- Node 基线：`>=18.12.0`（项目实践通常使用 Node 20）
- 端口契约见 `docs/apps-techniques.md`，未经用户明确要求不得修改。

## 9. 常用命令
见 `package.json` 的 `scripts`。常用入口：`pnpm install`、`pnpm dev`、`pnpm build`、`pnpm lint`。

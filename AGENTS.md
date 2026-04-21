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
  - KnowledgeChatPanel：`packages/docs-ui/src/components/common/widgets/KnowledgeChatPanel.vue`
  - SOPChatPanel：`packages/docs-ui/src/components/common/widgets/SOPChatPanel.vue`
  - SOPTree：`packages/docs-ui/src/components/common/widgets/SOPTree.vue`
  - SmartTree：`packages/ui-kit/src/components/common/SmartTree.vue`
- `web-console` 与 `admin-console` 默认保持行为一致，除非需求明确区分。
- 优先扩展既有协议和适配器，避免平行实现。

## 5. 执行契约

### 5.1 编码前
- 编码前先思考:不确定时要询问，不要默默选择一种解释就直接开始
- 简约至上:代码最简化，任何过度设计都一目了然
- 精确编辑:只修改必要的部分，不要顺便修复旁边的代码
- 目标驱动:在开始前将模糊的指令转化为可验证的目标

### 5.2 编码前
- 检查相邻文件的风格、导入与实现模式。
- 引入新依赖前先确认仓库已使用或确有必要。
- 在动手前明确验收标准与验证方式。

### 5.3 编码中
- 对于Python文件，需要在函数上方增加一句话注释，说明函数的功能。
- 不把无关重构混入功能或缺陷修复。
- 非迁移任务不随意破坏已有 API 契约。
- Vite 配置以 `vite.config.ts` 为唯一真相源，不保留同名 `vite.config.js` 副本。
- 禁止写入密钥、凭据和环境敏感信息。
- 对于 Vue 3 项目，涉及第三方库（如 pdf.js）的对象时，若其内部包含原生私有字段（以 # 开头），必须使用 `shallowRef` 而非 `ref`，以避免 Proxy 代理导致的私有字段访问错误。
- PDF 渲染优化准则：
  - 必须在渲染前填充白色背景（`fillStyle = '#ffffff'`），确保在深色模式或不同背景下颜色显示一致。
  - 设置 Canvas 尺寸前必须校验是否发生变化，避免因重复设置尺寸导致 Canvas 被清空而产生的闪烁。
  - 必须对容器使用 `ResizeObserver` 监听尺寸变化，以实现准确的自适应缩放。
  - 使用 `shallowRef` 存储 `ResizeObserver` 实例以避免潜在的私有字段访问错误。

- 主题与样式开发规范（Theme & Style Guardrails）：
  - **唯一真相源**：所有组件的主题状态（亮/暗模式）必须统一通过 `@angineer/ui-kit` 的 `useTheme()` 获取。严禁在组件内私自使用 `window.matchMedia` 获取系统主题，严禁通过组件层层传递 `darkMode` Props（Prop Drilling）。
  - **避免局部硬编码**：禁止在各个组件的 `<style>` 中写死诸如 `.dark-mode { background: #0f141d; }` 的局部暗黑颜色覆盖。必须使用全局 CSS 变量（如 `var(--dp-pane-bg)`），并在全局或顶层统一声明不同主题下的变量值。
  - **弹窗样式隔离**：对于挂载到 `body` 上的弹窗组件（如 Modal），严禁为了覆盖深色样式而移除 `<style scoped>` 导致样式污染全局。必须通过 `wrapClassName` 传入主题类名，并配合特定的命名空间（如 `.index-tree-modal`）进行安全隔离。

### 5.3 编码后
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

### 8.1 端口契约（强约束）
- 对外访问端口：
  - `apps/web-console`：`3005`
  - `apps/admin-console`：`3002`
- 对内 API 端口：
  - `apps/api-server/main.py`：`8033`
  - 前端开发代理 `/api` 必须指向 `http://localhost:8033`
- 未经用户明确要求，不允许修改上述端口；如必须调整，必须在同一次变更中同步更新所有引用点并完成验证。

## 9. 常用命令
- 安装依赖：`pnpm install`
- 启动全部：`pnpm dev`
- 启动前台：`pnpm dev:frontend`
- 启动后台：`pnpm dev:admin`
- 启动后端：`pnpm dev:backend`
- 构建全部：`pnpm build`
- 代码检查：`pnpm lint`
- Harness 测试：`pnpm harness`
- 同步技术文档：`pnpm docs:sync`
- 校验技术文档：`pnpm docs:check`

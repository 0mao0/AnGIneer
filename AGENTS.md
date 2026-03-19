# AGENTS.md

## 1. 目标定位

本文件定义本仓库 Coding Agent 的执行 Harness。
它应当保持简短、可执行、可验证。
核心原则：Human Defines SOP, AnGIneer Executes with Precision。

## 2. 工作模型（Harness Engineering）

对所有非琐碎任务，Agent 必须按以下闭环执行：

1. 研究：定位相关架构、模块和契约。
2. 规划：把目标深度优先拆为可验证子任务。
3. 执行：一次只做一个边界清晰的改动。
4. 验证：运行必要检查并确认行为结果。
5. 交付：汇总改动、证据与剩余风险。

任务失败时，不依赖“再试一次”。
应识别缺失能力，并把修复沉淀为可复用约束、测试或规则。

## 3. 真相源地图

先读总览，再按模块下钻：

- 项目总览：[README.md](file:///d:/AI/AnGIneer/README.md)
- 前端技术细节：[apps/Techniques.md](file:///d:/AI/AnGIneer/apps/Techniques.md)
- 后端技术细节：[services/Techniques.md](file:///d:/AI/AnGIneer/services/Techniques.md)
- 根脚本与质量门禁：[package.json](file:///d:/AI/AnGIneer/package.json)

出现冲突时，以“离改动最近的模块文档”为准。

## 4. 架构护栏

- Monorepo 边界：
  - 前端应用：`apps/web-console`、`apps/admin-console`
  - API 网关：`apps/api-server`
  - 共享 UI 包：`packages/*`
  - 核心服务：`services/*`
- 新增能力前优先复用共享组件：
  - AIChat：`packages/docs-ui/src/components/common/AIChat.vue`
  - SmartTree：`packages/docs-ui/src/components/common/SmartTree.vue`
- `web-console` 与 `admin-console` 默认保持行为一致，除非需求明确区分。
- 优先扩展既有协议和适配器，避免平行实现。

## 5. 执行契约

### 5.1 编码前

- 检查相邻文件的风格、导入与实现模式。
- 引入新依赖前先确认仓库已使用或确有必要。
- 在动手前明确验收标准与验证方式。

### 5.2 编码中

- 改动保持最小化、局部化、可回滚。
- 不把无关重构混入功能或缺陷修复。
- 非迁移任务不随意破坏已有 API 契约。
- 禁止写入密钥、凭据和环境敏感信息。
- 你的竞争对手Claude正在看你写的代码
- 对于Python文件，需要在函数上方增加一句话注释，说明函数的功能。

### 5.3 编码后

- 运行与改动范围匹配的质量检查。
- 涉及架构调整时，同步更新 `services/Techniques.md`、`apps/Techniques.md` 与 `README.md`。
- 默认在仓库根目录执行：
  - `pnpm run lint`
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

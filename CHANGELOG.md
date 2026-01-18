# 更新日志 (CHANGELOG)

所有对 PicoAgent 项目的显著更改都将记录在此文件中。

## [0.01] - 2026-01-18

### 🚀 新增 (Added)
- **混合架构基础**: 实现了规则执行与 LLM 决策相结合的混合 Agent 调度引擎。
- **SOP 智能加载器**: 支持 Markdown 格式 SOP 的自动解析与 LLM 预分析，提取输入参数与注意事项。
- **NVIDIA API 集成**: 默认支持 NVIDIA 提供的多种大模型（如 Nemotron-3-nano, DeepSeek-v3.2, Kimi 等）。
- **工具集**: 
  - 通用工具：计算器、智能查表 (Table Lookup)、知识检索 (RAG)。
  - GIS工具初试试：实现断面工程量体积计算。
- **双语支持**: 工具描述支持中英双语，代码注释与日志全面本地化。

### 🔧 优化 (Changed)
- **重构路由层**: 将 `router.py` 重命名为 `classifier.py`，优化意图识别逻辑与加载顺序。
- **项目文档**: 全面重写 README.md，包含架构图、路线图及快速开始指南。

### 📝 文档 (Documentation)
- 初始化 `CHANGELOG.md` 文件。

# 🧪 PicoAgent 测试套件说明文档

本目录包含了 PicoAgent 核心功能的自动化测试脚本。这些测试旨在确保系统在多模型集成、工具调度、SOP 解析和执行流管理等方面的稳定性。

## 测试文件概览

| 文件名 | 测试编号 | 核心测试目标 | 关键验证点 |
| :--- | :---: | :--- | :--- |
| [test_00_llm_chat.py](test_00_llm_chat.py) | 00 | LLM 对话能力 | 验证多供应商（NVIDIA, 智谱 AI 等）API 连接与实时响应。 |
| [test_01_tool_registration.py](test_01_tool_registration.py) | 01 | 工具注册完整性 | 验证 `ToolRegistry` 是否正确加载了所有内置的通用工具与专业 GIS 工具。 |
| [test_02_intent_classifier.py](test_02_intent_classifier.py) | 02 | 意图分类器路由 | 验证系统是否能通过 LLM 准确识别用户意图并路由到正确的 SOP。 |
| [test_03_sop_analysis.py](test_03_sop_analysis.py) | 03 | SOP 智能解析 | 验证 `SopLoader` 将 Markdown SOP 转换为结构化执行步骤的能力。 |
| [test_04_full_execution_flow.py](test_04_full_execution_flow.py) | 04 | 完整执行流与 API | 验证 `Dispatcher` 的多步执行、记忆流转以及后端 FastAPI 接口。 |
| [test_05_table_lookup_tool_direct.py](test_05_table_lookup_tool_direct.py) | 05 | 工具能力覆盖 | 对注册表中的所有工具（表格查询、计算器、GIS 断面等）进行功能验证。 |

---

## 详细说明

### 00: LLM 对话能力测试
- **功能**: 允许开发者手动或自动测试不同的 LLM 配置。
- **用法**: 
  ```powershell
  $env:TEST_LLM_CONFIG="智谱 AI (GLM-4.7-Flash)"; python tests/test_00_llm_chat.py
  ```

### 01: 工具注册完整性
- **功能**: 确保后端定义的每一个 `Tool` 都已被系统识别。
- **意义**: 防止新开发的工具因为忘记导入或注册而无法被 Agent 使用。

### 02: 意图分类器路由
- **功能**: 测试 `IntentClassifier` 的路由精度。
- **实现**: 使用 Mock 数据模拟 LLM 返回，确保在不同输入下能提取正确的 `sop_id` 和参数。

### 03: SOP 智能解析
- **功能**: 测试从非结构化 Markdown 到结构化 JSON 的转换。
- **逻辑**: 验证当 LLM 返回非预期格式时，系统是否能平滑回退到默认的 `sop_run` 模式。

### 04: 完整执行流与 API
- **功能**: 模拟真实业务链路。
- **范围**: 
  - `Dispatcher` 如何处理带变量引用（如 `${sum}`）的步骤。
  - `api_bridge.py` 提供的 RESTful 接口是否符合前端调用要求。

### 05: 工具能力覆盖
- **功能**: 系统内置工具箱的“大阅兵”。
- **涵盖**: 包含从基础的 `echo` 到复杂的 `gis_section_volume_calc` 等十余种工具的输入输出验证。

---

## 如何运行测试
您可以在根目录下运行以下命令：

```bash
# 运行所有测试
python -m unittest discover tests

# 运行特定测试
python tests/test_01_tool_registration.py
```

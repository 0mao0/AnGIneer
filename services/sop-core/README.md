# angineer-sop-core

SOP（标准作业流程）**编写库**：加载 / 解析 / 校验 / 生成。**不含执行**——
`SOP` / `Step` 契约与 `sop_execute` 执行器在 [angineer-core](https://pypi.org/project/angineer-core/)；
本库不连数据库、不做检索，图谱读取由消费方按 `GraphReader` 协议注入。

| 能力 | 入口 | 依赖 |
| :--- | :--- | :--- |
| 加载（json/、raw/ → SOP，index.json 生成，状态过滤） | `SopLoader` | 无（纯本地目录） |
| 校验（步骤图 / 变量闭包 / 表达式 / 工具名） | `validate_sop_data`、`validate_sop` | 无 |
| 解析（步骤描述 → 工具/inputs/outputs 绑定） | `SopParser` | LLM 可选（失败回退规则） |
| 生成（图谱框架路径 → 完整 SOP） | `SopPathGenerator` | 图谱端口 + LLM |

## 安装

```bash
pip install angineer-sop-core
```

## 加载

```python
from sop_core import SopLoader

loader = SopLoader("<sop_base_dir>")   # 目录内放 json/（可选 raw/、index.json）
sops = loader.load_all()               # 缺省只取 published；index.json 缺失时自动生成
print([s.name_zh for s in sops])
```

- 目录布局：`json/<id>.json` 为唯一真相源；`raw/*.md` 仅作兼容数据源（json 未注册时才收录）；
  `index.json` 是生成物，`SopLoader` 会按文件信号（index.json mtime + json/、raw/ 快照）自动失效重建。
- 缓存：进程内按文件信号失效，`ANGINEER_SOP_CACHE_TTL` 只作兜底（默认 300 秒，`0` 停用缓存）。
- 状态：JSON 里无 `status` 键即视为 `published`；`draft` / `disabled` 需显式声明，
  `load_all(include_status=("published", "draft"))` 可放宽。

## 校验

```python
from sop_core.sop_validator import validate_sop_data

problems = validate_sop_data({"name_zh": "...", "steps": [...]})
# 空列表 = 通过；否则是逐条问题描述（步骤图环/悬空引用、变量闭包不可达、
# calculator 缺 expression、工具名不认识等）
```

## 生成

```python
from sop_core import SopPathGenerator
from sop_core.graph_port import GraphReader   # 消费方实现的只读图谱端口（8 个方法）

gen = SopPathGenerator(store=my_graph_reader, config_name=None)  # config_name 交给 ai-inference 默认配置
sop = gen.generate_sop_from_steps("框架名", ["步骤 1", "步骤 2"],
                                  source_section="出处", library_id="...", doc_id="...")
```

- LLM 优先、失败回退确定性骨架；LLM 调用经 `angineer-ai-inference` 的 `LLM_CONFIGS`。
- `graph_port` 只定协议不给实现：本地直连（GraphStore）或 HTTP 适配都行，
  实体层字符串常量（`LAYER_CONCEPT`/`LAYER_CONDITION`/`LAYER_ACTION`）与文档解析侧对齐。
- 落盘：`SopLoader.save_generated_sop(...)` 显式写 `json/`；
  生成器内部的「参考 SOP 读取 / 批量落盘」目录取 `$DATA_DIR`（缺省 `<当前目录>/data/platform/sops`），
  独立使用时请显式设置该环境变量。

## 测试

```bash
pip install -e . pytest
pytest tests -q
```

## 相关仓库

| 包 | 职责 |
| :--- | :--- |
| [angineer-core](https://pypi.org/project/angineer-core/) | SOP 契约（`SOP`/`Step`）+ `sop_execute` 执行器 + 问答编排 |
| [angineer-ai-inference](https://pypi.org/project/angineer-ai-inference/) | LLM 客户端（多端点路由 / 重试 / 熔断） |
| [angineer-docs-core](https://pypi.org/project/angineer-docs-core/) | 文档解析入库（图谱实体由 `GraphReader` 侧提供） |

## License

MIT

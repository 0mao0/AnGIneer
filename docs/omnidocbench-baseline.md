# OmniDocBench 解析质量基线（200 页抽样）

2026-09-12 首次在**开发机**跑通完整解析质量评测：本机 in-process 驱动生产解析链产出预测，
官方评测器镜像（Docker）算指标。此文件是内部回归跟踪的基准口径——改解析链（MinerU/PoPo/Solo/prompt）后
重跑同一集合，与本表逐项对比即可判断涨跌。

## 评测集合定义（重跑必须一致）

| 项 | 值 |
|---|---|
| 数据 | OmniDocBench v1.6.0，`D:/AI/tools/OmniDocBench_data`（1651 页 GT 在仓库外） |
| 抽样 | `--limit 200 --seed 42`（在 1651 页中均匀随机抽样，按文档类型自然配比，共 10 类） |
| 预测目录 | `data/evals/omnidocbench/predictions_eval200/`（200/200 成功，零失败） |
| 结果目录 | `data/evals/omnidocbench/result_eval200/` |
| 解析链 | source_prep → convert → raw_parse(MinerU) → popo → structure（`use_llm=False`，纯规则 structure） |
| 预测耗时 | 52 分钟 / 200 页 = **17.5s/页**（全量 1651 页推算约 8 小时） |

```bash
# ① 本机解析（无需容器，docs_core 可直接导入，.env 自动加载）
python scripts/run_omnidocbench_eval.py predict --in-process \
    --data-dir D:/AI/tools/OmniDocBench_data \
    --predictions data/evals/omnidocbench/predictions_eval200 --limit 200 --seed 42
# ② 本机评测（官方镜像 ghcr.io/zeng-weijun/omnidocbench-eval，18.1GB）
python scripts/run_omnidocbench_eval.py eval --data-dir D:/AI/tools/OmniDocBench_data \
    --predictions data/evals/omnidocbench/predictions_eval200 \
    --out data/evals/omnidocbench/result_eval200
```

## 总基线（200 页）

| 指标 | 值 | 方向 |
|---|---|---|
| 文本 Edit_dist | **0.0813** | 越低越好 |
| 表格 TEDS | **0.8821** | 越高越好 |
| 表格 TEDS_structure_only | 0.8985 | 越高越好 |
| 公式 Edit_dist（LaTeX 串） | 0.1116 | 越低越好 |
| 公式 CDM | 0.9509 | 越高越好 |
| 阅读顺序 Edit_dist | **0.1503** | 越低越好 |

注：与 6 页冒烟批次的数字（文本 0.110 / TEDS 0.972 / 阅读顺序 0.076）**不可直接比较**——
页集合不同，且 6 页样本恰好偏易。以本表为基准。

## 分文档类型（`page_attribute.data_source`）

| data_source | 页数 | 文本 Edit_dist | 表格 TEDS | 公式 Edit_dist | CDM | 阅读顺序 |
|---|---|---|---|---|---|---|
| PPT2PDF | 36 | 0.087 | 0.878 | 0.047 | 0.996 | 0.091 |
| book | 32 | 0.149 | 0.984 | 0.156 | 0.939 | 0.191 |
| academic_literature | 20 | 0.081 | 0.866 | 0.078 | 0.982 | 0.129 |
| colorful_textbook | 19 | 0.076 | 0.923 | **0.224** | **0.854** | 0.135 |
| exam_paper | 19 | 0.151 | 0.982 | 0.041 | 0.962 | 0.097 |
| newspaper | 19 | 0.021 | **0.607** | - | - | 0.107 |
| magazine | 18 | 0.029 | - | - | - | 0.056 |
| research_report | 14 | 0.003 | 0.884 | - | - | **0.400** |
| note | 10 | 0.010 | 0.925 | - | - | 0.103 |
| historical_document | 1 | 0.400 | - | - | - | 0.871 |

（`-` = 该类型无此要素的样本，非 0 分。末行 n=1，不具统计意义。）

## 分语言 / 版式

| 维度 | 值 | 页数 | 文本 | 表格 TEDS |
|---|---|---|---|---|
| language | simplified_chinese | 88 | 0.076 | 0.923 |
| | english | 82 | 0.083 | **0.826** |
| | en_ch_mixed | 15 | 0.092 | 0.959 |
| layout | single_column | 100 | 0.091 | 0.876 |
| | other_layout | 44 | 0.111 | **0.685** |
| | double_column | 23 | 0.031 | 0.984 |
| | 1andmore_column | 13 | 0.005 | 0.965 |

## 结论：优先修三处

1. **表格解析是最大短板**——整体 TEDS 0.882，`newspaper` 仅 0.607、`other_layout` 0.685、英文表格 0.826。
   复杂版式（多栏混排/报纸）下的表格结构识别明显弱于规整版式（double_column 0.984）。
2. **阅读顺序在 research_report 上崩**（0.400，样本 14 页），`book` 0.191 次之——长文档/多栏的块序重建需查。
3. **公式在 colorful_textbook 上差**（CDM 0.854 / Edit_dist 0.224），教材类公式排版复杂度可能是主因。

## 相关文件

- 脚本：`scripts/run_omnidocbench_eval.py`（predict / eval 两个子命令，断点续跑）
- 回归测试：`tests/unit/test_unit_omnidocbench_predict_clean.py`（锁 build_id 注释头不得进预测）
- 镜像获取与拆分执行说明：脚本 docstring 头部

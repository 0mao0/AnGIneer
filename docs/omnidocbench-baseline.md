# OmniDocBench markdown 交付面基线（200 页抽样）

> **口径定位（2026-09-12 更正）**：本文件记录的是**官方 markdown 口径**——把我们的
> `content.md` 交给官方评测器，由对方把 markdown 再切块后与 GT 比对。它量的是
> **「我们交付的 markdown 有多好」**（预览/编辑/导出/step07 图谱抽取/agent 的 table_lookup
> 消费这一层），**不是** pipeline 的解析质量——RAG 检索吃的是 canonical jsonl / SQLite / 向量
> 那一层，本口径完全不量（块层级、section_path、chunk 边界、表格检索表示都不进分）。
> **要看 pipeline 解析质量，用 `docs/parse-structure-eval.md` 的结构层口径。**

2026-09-12 首次在**开发机**跑通完整 markdown 口径评测：本机 in-process 驱动生产解析链产出预测，
官方评测器镜像（Docker）算指标。

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

| data_source | 页数 | 表数 | 文本 Edit_dist | 表格 TEDS | 公式 Edit_dist | CDM | 阅读顺序 |
|---|---|---|---|---|---|---|---|
| PPT2PDF | 36 | 6 | 0.087 | 0.878 | 0.047 | 0.996 | 0.091 |
| book | 32 | 6 | 0.149 | 0.984 | 0.156 | 0.939 | 0.191 |
| academic_literature | 20 | 21 | 0.081 | 0.866 | 0.078 | 0.982 | 0.129 |
| colorful_textbook | 19 | 3 | 0.076 | 0.923 | **0.224** | **0.854** | 0.135 |
| exam_paper | 19 | 5 | 0.151 | 0.982 | 0.041 | 0.962 | 0.097 |
| newspaper | 19 | 4 | 0.021 | 0.607 | - | - | 0.107 |
| magazine | 18 | 0 | 0.029 | - | - | - | 0.056 |
| research_report | 14 | 24 | 0.003 | 0.884 | - | - | **0.400** |
| note | 10 | 4 | 0.010 | 0.925 | - | - | 0.103 |
| historical_document | 1 | 0 | 0.400 | - | - | - | 0.871 |

**表格列的小样本警告**：整批只有 73 张表，且 76% 集中在 research_report(24) 与 academic_literature(21)；
newspaper 的 0.607 仅由 4 张表支撑，book/PPT2PDF/exam_paper 各 5–6 张——**分类型表格数字只作线索，不作结论**。
可靠的表格结论是全批 73 张的 **TEDS 0.8821 / structure_only 0.8985**。全批 73 张里有 **2 张 TEDS=0.0**。

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

1. **表格解析是最大短板**——全批 73 张表 TEDS 0.882（structure_only 0.8985），其中 2 张 0.0。
   已定位一例根因：`newspaper_Daily Star..._page_060` 页面上两张 9×9 数独表被**合并成一张 18 行表**
   （GT 两张、预测一张），导致第 2 张无对应 → TEDS 0.0、第 1 张被拉成 0.5。**相邻同构表格未切分**是明确缺陷。
2. **阅读顺序在 research_report 上崩**（0.400，14 页 24 表，样本充足），`book` 0.191 次之——长文档/多栏的块序重建需查。
3. **公式在 colorful_textbook 上差**（CDM 0.854 / Edit_dist 0.224，19 页），教材类公式排版复杂度可能是主因。

## 评测吃的是 markdown，不是 pipeline 的 JSON

`predict` 提交给官方评测器的是 `parsed/content.md`（markdown），**不是** `doc_blocks_graph.jsonl` /
`mineru_raw/content_list.json` 这些带 bbox、block_seq 的结构化产物。官方 end2end 评测器
`_resolve_prediction_path` 只解析 `.md`（镜像内 `/workspace/src/dataset/end2end_dataset.py:2001-2014`），
读入后**由评测器自己把 markdown 再切成块**，与 GT JSON 的块做匹配后算指标。

含义：
- 指标反映"我们的结构信息有多少活过了 markdown 投影"——块角色、层级、bbox 不直接参与打分；
- 表结构按 markdown 表格（转 HTML）算 TEDS，阅读顺序按 markdown 块序算；
- 想直接评 JSON 结构，官方另有 `layout_detection.yaml` / `table_recognition.yaml` / `formula_recognition.yaml`
  任务（配置在镜像里），需要把我们的 JSON 转成官方 schema——我们的
  `mineru_raw/content_list.json`（`type/text/bbox/page_idx`）与 `doc_blocks_graph.jsonl`
  （`block_type/plain_text/bbox/block_seq`）字段已齐，转换可行但尚未做。

## 相关文件

- 脚本：`scripts/run_omnidocbench_eval.py`（predict / eval 两个子命令，断点续跑）
- 回归测试：`tests/unit/test_unit_omnidocbench_predict_clean.py`（锁 build_id 注释头不得进预测）
- 镜像获取与拆分执行说明：脚本 docstring 头部

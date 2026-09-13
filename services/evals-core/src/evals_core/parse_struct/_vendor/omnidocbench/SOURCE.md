# 来源与同步说明

## 上游

- 仓库：`opendatalab/OmniDocBench`（Apache-2.0）
- 取文件来源：评测镜像 `ghcr.io/zeng-weijun/omnidocbench-eval:repro-ubuntu2204`
  （该镜像是本仓库既有的官方评测通道，见 `scripts/run_omnidocbench_eval.py`）
- 镜像内路径：`/workspace/src/metrics/table_metric.py`
- 环境自报版本：镜像内 conda env `omnidocbench_v16_smoke_20260408_py310`（对应 OmniDocBench v1.6 系）
- 取文件时间：2026-09-12

## 保留了哪些

| 文件 | 用途 |
| --- | --- |
| `table_metric.py` | 表格 TEDS（`TEDS.evaluate(pred_html, true_html)`），原样搬运未改动 |
| `LICENSE` | 上游 Apache-2.0 许可证全文（原样搬运） |

**未搬运**：`table_utils.py`（markdown→HTML 转换，我们的输入本来就是 HTML，不需要）、
`metrics/cdm/*`（公式像素比对，依赖 TeX Live）、以及数据集/匹配器等其余部分。

## 维护约定

- **不做本地改写**：TEDS 的口径必须与官方镜像逐位一致，改一行就失去可比性。需要改行为时，
  改为在我们自己的代码里做输入归一（如 `jsonl_eval.norm_latex`），不要动这个文件。
- 上游若升级（GT 或镜像换代），重新从新镜像取文件、更新下面的指纹并重跑回归：
  - 依赖：`apted`（树编辑距离）、`Levenshtein`、`lxml`、`tqdm`
- 没有 vendor 整包的理由（2026-09-12 结论）：验收要求与官方镜像逐位一致（镜像不可退役）、
  砍 CDM 会断基线口径、整包约 3000 行维护债；而本目录只需要 400 行里的表格指标那部分。

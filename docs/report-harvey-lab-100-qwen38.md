# Harvey LAB firm-knowledge 复测报告（Qwen3.8 臂，100 题）

日期：2026-10-20　样本：firm-knowledge 001–100（连续 100 题，全部有答卷与判分）
题库：`harvey-firm-knowledge-v1`（250 题 / 2623 条 rubric）　语料：`lab-firm-full`（266 matter / 9009 篇）
判分：`lab_core.evaluation.scoring.score_rubric`，单判官 gpt-5.5，温度 0，`LAB_JUDGE_SKIP_STRUCTURED=1`

## 摘要

| 指标 | Qwen3.6（基线） | **Qwen3.8-Flash-Next** | 变化 |
|---|---|---|---|
| all-pass | 3.0%（3/100） | **9.0%（9/100）** | +6 题 |
| all-pass 95%CI | [1.0, 8.5] | **[4.8, 16.2]** | 上界翻倍 |
| criterion | 17.0%（133/783） | **27.5%（215/783）** | +82 条 |
| 退化输出 | 8 题 | **0 题** | 清零 |

参考：GLM-Legal 对外 19.2%（单点，未注明区间；官方默认双判官）。本臂仍低于该点估计，但差距从 6.4 倍收到约 2.1 倍，且置信区间上界已到 16.2%。

## 变化结构

68 题判据数相对基线变化：**51 升、17 降**，净 +82 条判据。

逐题 criterion 分布：

| 区间 | 基线 | Qwen3.8 |
|---|---|---|
| 0% | 36 | **16** |
| 1–49% | 43 | 53 |
| 50–99% | 18 | **22** |
| 100% | 3 | **9** |

all-pass 题：012、030、032、037、056、061、082、093、098。其中 030、032、037、056、082、093、098 为新增；012、061 两题在基线即 all-pass。

## 关键观察

1. **回显与空答消失**：基线 8 题退化（001/021/055/059/067/080/088/095），Qwen3.8 臂无 <100 字符答卷。此前 P1/P3/P0.5/P2.1/P2.2 五次链路实验都改不动的 001（回显），换模型后正常作答并拿到 4/7。
2. **长枚举题改善最大**：011（1→6/19）、030（0→6/6）、028（0→5/6）、019（0→4/12）、041（0→7/23）。
3. **仍有 17 题回落**（005 3→1、017 2→1、020 2→1、045 4→1 等），说明不是全面更强，需在报告里如实列出。

## 口径限定

- **单判官**：与基线同一 gpt-5.5 单判，未做双判平均；跨臂可比、与官方 19.2% 非严格同口径；
- **顺序样本**：001–100 连续题，非随机抽样；
- **仅换模型**：prompt、工具、检索参数、语料与基线完全一致；这是本臂唯一变量；
- 100 题全部判分完成，无缺卷。

## 复现

```powershell
# 生成臂（默认模型切到 Qwen3.8）
$env:ANGINEER_DEFAULT_MODEL="Qwen3.8-Flash-Next"
python services/aichat-api/main.py
python data/scratch/harvey-lab/tools/run_angineer_arm_par.py `
  --tasks 001-100 --label qwen38b --workers 3 --deadline 600 `
  --library lab-firm-full --key-file data/scratch/harvey-lab/runner_key_full.txt --skip-existing
python data/scratch/harvey-lab/tools/grade_arm_par.py --label qwen38b --workers 3 --judges gpt-5.5
```

逐题明细见 `data/scratch/harvey-lab/arm_report_qwen38b.json`（不入 git）。

## 结论与下一步

- **模型能力是此前所有链路改造都没触到的天花板**：同链路换模型，all-pass 3→9%、criterion 17→27.5%，且退化清零；
- 之前 P1/P3/P0.5/P2.1/P2.2 的“无效”结论需要重估——它们都在弱模型上做，强模型下证据绑定的边际收益可能不同；
- 下一步优先级：① 双判官复跑本臂（对齐官方口径）；② 在 Qwen3.8 上重做 P2（结构化证据绑定）；③ 分析 17 题回落是否为新模型稳定性问题。

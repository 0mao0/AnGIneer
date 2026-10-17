# -*- coding: utf-8 -*-
"""表型回归集 v1 生成器：从 std-water 语料抽 9 张真表快照 + 写入用例（expectations 人工核过）。

产物: services/angineer-core/tests/fixtures/table_type_regression_v1.json
用法: python services/angineer-core/tests/fixtures/build_table_type_regression.py

口径：
- expected = 真值（人工按快照核定，expected_why 写明怎么来的）
- baseline = 2026-10-16 修复前实测值（确定性通道实跑；读表通道取 q2020-007/q2019-009 实况）
- status: fixed（已正确，锁住）/ xfail（当前错，P2-x 修好后须改 fixed）
- channel: table_lookup=确定性引擎（离线可断值）；table_read=LLM 判读（离线只断选表，取值走 live 探针）
"""
import os
import sys
import json
import datetime

ROOT = "D:/AI/AnGIneer"
os.chdir(ROOT)
os.environ.setdefault("ANGINEER_DATA_ROOT", ROOT + "/data")
sys.path[:0] = [f"{ROOT}/services/{p}/src" for p in
                ("angineer-core", "docs-core", "sop-core", "engtools", "ai-inference")]

from docs_core.docs_service import docs_service
from angineer_core.table_query_engine import query_tables

LIB = "std-water"
OUT = "services/angineer-core/tests/fixtures/table_type_regression_v1.json"

# ── 表快照清单（table_id 取自语料，signatures 是它踩中的表型）
TABLES = [
    ("table-doc-11922bab:131:3", ["复式表头"],
     "散货/集装箱船船舶主要尺度实录表 A.0.2-1（子表头行在 body[0]，列名 总长L/型宽B/型深H/满载吃水T 不在 header）"),
    ("table-doc-11922bab:52:12", ["复式表头", "成对列", "区间列"],
     "船舶与航道底边线间的富裕宽度 c 表6.4.2-2（成对船型列 × 航速区间子表头）"),
    ("table-doc-11922bab:27:5", ["复式表头", "成对列"],
     "滚装船 Z3 表5.4.12-2（子表头行在 body[0]；成对吨级列 DWT/GT）"),
    ("table-doc-11922bab:24:7", ["复式表头", "成对列"],
     "潮位与波浪组合及富裕高度 表5.4.8（两层表头 + 上水/受力成对块）"),
    ("table-doc-11922bab:26:17", ["成对列"],
     "龙骨下最小富裕深度 Z1 表5.4.12-1（两组「海底底质+Z1」成对列）"),
    ("table-doc-11922bab:52:11", ["成对列", "区间列"],
     "船舶漂移倍数 n 与风、流压偏角 γ 表6.4.2-1（横流 V 区间列 + n/γ 指标行）"),
    ("table-doc-11922bab:54:1", ["区间列"],
     "航行时龙骨下最小富裕深度 Z1 表6.4.6-1（土质行 × 吨级区间列）"),
    ("table-doc-11922bab:54:2", ["区间列"],
     "船浪夹角 Ψ 与 Z2/H4% 系数表（caption 丢表号；T̄ 两行 × Ψ 列）"),
    ("table-doc-11922bab:128:3", ["复式表头", "区间列"],
     "集装箱船设计船型尺度表 A.0.1-4（吨级区间行 + 尺度子表头；3 个 SOP 步在用）"),

    # ── 2026-10-18 扩展（std-water doc-fbb3306e / JTS 154-2018，SOP 数值验证实踩） ──
    ("table-doc-fbb3306e:50:11", ["成对列", "LaTeX 表头"],
     "表6.2.3 波浪力分项系数 γP/γV/γu（目标列名带 γP 后缀 vs 表头 $\\gamma_{P}$；组合情况+稳定情况 双文本条件）"),
    ("table-doc-fbb3306e:37:8", ["LaTeX 表头"],
     "表5.3.6 波浪力分项系数 γP/γu（列名 $\\gamma_{P}$/$\\gamma_{u}$；单文本条件）"),
    ("table-doc-fbb3306e:28:15", ["横向成对双列", "区间列"],
     "表4.3.24 堤前护底块石稳定重量（Vmax|W|Vmax|W 四列一组横排；右半区若只扫首列会选错行）"),
    ("table-doc-fbb3306e:13:6", ["两级列", "区间值"],
     "表3.1.18 摩擦系数设计值（材料两级列；值含 0.50~0.60 范围文本）"),
    ("table-doc-fbb3306e:23:10", ["子表头行在 body[0]"],
     "表4.3.7 稳定系数 K_D（真列名「护面块体/构造型式」在 body[0]；SOP 用 header 可见键「护面型式」+行文本条件适配）"),
]

# ── 用例（期望值人工核定；baseline 见脚本尾部实跑）
CASES = [
    # id, table_id, channel, signature, table_name, conditions, target, expected, expected_why, baseline_mode, status, note
    ("A1-实录表-型宽B", "table-doc-11922bab:131:3", "table_lookup", "复式表头", "表A.0.2-1",
     {"载重吨DWT(t)": "45071"}, "型宽B", 32.2,
     "载重吨 45071 命中第4行 CCNI Potrerillos，型宽B=32.2（型宽B 列名住在 body[0] 子表头行）",
     "row_dict", "xfail", "P2-1 靶区：行命中了但目标列找不到（header 里只有重复的「船舶主要尺度(m)」）→ 引擎回落返回整行字典，链路取不到标量"),

    ("A2-c系数", "table-doc-11922bab:52:12", "table_read", "复式表头", "表6.4.2-2",
     {"船型": "集装箱船", "航速(kn)": "8"}, "c的系数（纯数字；0.50B→0.5，B→1.0，1.50B→1.5）", 0.75,
     "杂货船或集装箱船 × 航速>6kn → 0.75B → 0.75（宽度 SOP step_5 原样查询）",
     0.75, "fixed", "宽度 SOP 在用；live 首测=0.75（2026-10-16，夹具 provider + 真 LLM）"),

    ("A3-Z3滚装船", "table-doc-11922bab:27:5", "table_lookup", "成对列", "表5.4.12-2",
     {"船舶吨级": "1000"}, "Z3", 0.30,
     "吨级≤1000 → Z3=0.30（目标列名 Z3 与表里 $Z_{3}$ (m) 需归一化）",
     None, "fixed", "2026-10-18 修复：LaTeX 符号剥离变体定位目标列（Z3 → $Z_{3}$ (m)）；"
     "修复前目标列未定位返回整行字典"),

    ("A4-潮位波浪-ΔF", "table-doc-11922bab:24:7", "table_lookup", "复式表头", "表5.4.8",
     {"组合情况": "基本标准"}, "受力标准下的富裕高度 ΔF（m）", "0~1.0m",
     "基本标准 × 受力标准 → ΔF 取 0~1.0m（上层表头「受力标准」× 子表头「富裕高度 ΔF」）",
     "text", "xfail", "当前返回「设计高水位」（首个文本格）——两层表头合并没有建模"),

    ("B1-Z1-底质条件键", "table-doc-11922bab:26:17", "table_lookup", "成对列", "表5.4.12-1",
     {"底质条件": "含砂或含粘土的块状土"}, "Z1", 0.40,
     "值文本落在第1行第二组「海底底质」对 → 其配对 Z1=0.40（成对列按值文本定位的正路）",
     None, "fixed", "P0-1 修复的已验证路径：条件键用 SOP 口径「底质条件」，锁住防回归"),

    ("B2-Z1-单位后缀目标列", "table-doc-11922bab:26:17", "table_lookup", "成对列", "表5.4.12-1",
     {"海底底质": "含砂或含粘土的块状土"}, "Z1 (m)", 0.40,
     "同上真值 0.40；只是目标列写成带单位形式「Z1 (m)」（B1 用裸「Z1」时正确）",
     None, "fixed", "2026-10-18 修复：LaTeX/符号剥离变体使目标列可解析（$Z_{1}$ (m)）"
     "＋成对列校正把目标列对齐到条件命中列（海底底质 col2 → Z1 col3）；修复前取首组 0.20"),

    ("B3-n", "table-doc-11922bab:52:11", "table_read", "区间列", "表6.4.2-1",
     {"横风风力(级)": "6", "横流V(m/s)": "0.31"}, "n", 1.69,
     "V=0.31 落在「0.25 < V≤0.50」列 → n=1.69（宽度 SOP step_3 原样查询；该值已在生产链验证）",
     1.69, "fixed", "live 首测=1.69（2026-10-16）；该值已在生产宽度链验证"),

    ("B4-γ", "table-doc-11922bab:52:11", "table_read", "区间列", "表6.4.2-1",
     {"横风风力(级)": "6", "横流V(m/s)": "0.31"}, "γ(°)", 7,
     "同上列 → γ=7（宽度 SOP step_3b）",
     7, "fixed", "live 首测=7（2026-10-16）；宽度 SOP step_3b 口径"),

    ("C1-Z1-吨级区间列", "table-doc-11922bab:54:1", "table_read", "区间列", "表6.4.6-1",
     {"土质特性": "坚硬粘性土", "船舶吨级(t)": "150000"}, "龙骨下最小富裕深度Z1（m）", 0.70,
     "150000 落在「100000≤DWT<300000」列，坚硬粘性土行 → 0.70（q2020-007 gold 口径）",
     0.60, "xfail", "P2-7 靶区：live 实况 0.60（cell 写对列名、值取邻列）"),

    ("C2-Z2系数-T8行", "table-doc-11922bab:54:2", "table_read", "区间列",
     "船、浪夹角\\Psi与Z_{2}/H_{4\\%}的变化系数值", {"船浪夹角Ψ(°)": "20"}, "Z2/H4%（T̄≤8s 行）", 0.38,
     "Ψ=20° 列 × T̄≤8s 行 → 0.38（P2-4 SOP step_5b 真值）",
     0.38, "fixed", "表号在 caption 里丢失 → 选表靠 caption 原文（score 220），锁住 P2-4 解法"),

    ("C3-集装箱-T", "table-doc-11922bab:128:3", "table_read", "区间列", "表A.0.1-4",
     {"船舶吨级DWT(t)": "5000"}, "满载吃水T", 6.9,
     "吨级 5000 落在「5000(4501~7500)」行 → 满载吃水T=6.9（q2019-009 实况，与 gold 一致）",
     6.9, "fixed", "航道 SOP step_1 原样查询（q2019-009 实况已核）"),

    ("C4-集装箱-B", "table-doc-11922bab:128:3", "table_read", "区间列", "表A.0.1-4",
     {"船舶吨级DWT(t)": "5000"}, "型宽B", 19.2,
     "同上行 → 型宽B=19.2（宽度 SOP step_1b 原样查询）",
     19.2, "fixed", "live 首测=19.2（2026-10-16）——同一张复式表头表，读表判读能在子表头行里取对型宽B，"
     "确定性引擎却做不到（见 A1/D1 对照）"),

    ("D1-target失配不猜", "table-doc-11922bab:128:3", "table_lookup", "复式表头", "表A.0.1-4",
     {"船舶吨级DWT(t)": "5000"}, "满载吃水T(m)", "no_scalar",
     "目标列「满载吃水T(m)」在表头不存在 → 不得返回任何标量（P2-3 验收：返回整行或明确 error）",
     121.0, "xfail", "P2-3 实锤：现返回 121.0＝总长L（吨级行首个数），静默错列"),

    # ── 2026-10-18 扩展（SOP 数值验证实踩：LaTeX 目标列 / 横向成对双列 / 含数字文本值） ──
    ("E1-γP后缀目标列", "table-doc-fbb3306e:50:11", "table_lookup", "LaTeX 表头", "表6.2.3",
     {"组合情况": "持久组合", "稳定情况": "抗滑"}, "水平波浪力分项系数γP", 1.25,
     "持久组合×抗滑 → γP=1.25（规范表6.2.3；SOP 半圆堤链 step_2 原样查询）",
     None, "fixed", "2026-10-18 修复：目标「…系数γP」经符号剥变体对齐表头 $\\gamma_{P}$（修复前 target 失配回落成对列，返回「抗滑」字符串）"),

    ("E2-γV后缀目标列", "table-doc-fbb3306e:50:11", "table_lookup", "LaTeX 表头", "表6.2.3",
     {"组合情况": "持久组合", "稳定情况": "抗滑"}, "竖向波浪力分项系数γV", 1.25,
     "持久组合×抗滑 → γV=1.25（同上表；修复前返回「抗滑」字符串）",
     None, "fixed", "同 E1：γV 与 $\\gamma_{V}$ 归一对齐"),

    ("E3-γu短暂组合", "table-doc-fbb3306e:50:11", "table_lookup", "LaTeX 表头", "表6.2.3",
     {"组合情况": "短暂组合", "稳定情况": "抗滑"}, "波浪浮托力分项系数γu", 1.2,
     "短暂组合×抗滑 → γu=1.2（规范表6.2.3 短暂组合取 1.2）",
     None, "fixed", "修复前靠 γu 小写 u 误中 key_parts 正则侥幸命中；现走正规变体对齐"),

    ("E4-横向成对右半区", "table-doc-fbb3306e:28:15", "table_lookup", "横向成对双列", "表4.3.24",
     {"堤前最大波浪底流速Vmax": 3.835}, "护底块石稳定重量W", 300,
     "V=3.835 落在右半区「3.6~4.0」→ W=300~400 取下限 300（规范表4.3.24；SOP step_30 口径）",
     None, "fixed", "2026-10-18 修复：数值条件扫全部同名列（0,2），区间单元格按区间判距选行；"
     "成对列校正把目标对齐到命中组（修复前选 3.1~3.5 行且目标未定位返回整行）"),

    ("E5-横向成对左半区", "table-doc-fbb3306e:28:15", "table_lookup", "横向成对双列", "表4.3.24",
     {"堤前最大波浪底流速Vmax": 2.3}, "护底块石稳定重量W", 60,
     "V=2.3 落在左半区「2.0~2.5」→ W=60~100 取下限 60",
     None, "fixed", "成对列校正随命中组选左组目标列（m+1=1）"),

    ("E6-横向成对右边界", "table-doc-fbb3306e:28:15", "table_lookup", "横向成对双列", "表4.3.24",
     {"堤前最大波浪底流速Vmax": 3.6}, "护底块石稳定重量W", 300,
     "V=3.6 是右半区下边界 → W=300~400 取 300（左半区上界 3.5 不命中）",
     None, "fixed", "区间命中优先（dist=0）压过左列近似（3.6-3.5=0.1×10=1）"),

    ("E7-γP带组合键", "table-doc-fbb3306e:37:8", "table_lookup", "LaTeX 表头", "表5.3.6",
     {"组合情况": "持久组合"}, "水平波浪力分项系数γP", 1.3,
     "持久组合 → γP=1.3（规范表5.3.6；圆筒堤链 step_6 原样查询）",
     None, "fixed", "修复前靠成对列兜底恰取相邻 γP 列侥幸正确；现正路解析 $\\gamma_{P}$"),

    ("E8-γu带组合键", "table-doc-fbb3306e:37:8", "table_lookup", "LaTeX 表头", "表5.3.6",
     {"组合情况": "短暂组合"}, "波浪浮托力分项系数γu", 1.2,
     "短暂组合 → γu=1.2（规范表5.3.6）",
     None, "fixed", "修复前兜底取到 γP 列（该表两列值相同故侥幸正确）；现正路对齐 $\\gamma_{u}$"),

    ("E9-摩擦系数两级列", "table-doc-fbb3306e:13:6", "table_lookup", "两级列", "表3.1.18",
     {"材料": "墙身为预制混凝土结构"}, "摩擦系数", 0.6,
     "墙底与抛石基床顶面×预制混凝土结构 → f=0.60（规范表3.1.18）",
     None, "fixed", "锁住既有正确路径（材料两级列表头展开后子串命中）"),

    ("E10-摩擦系数范围值", "table-doc-fbb3306e:13:6", "table_lookup", "两级列", "表3.1.18",
     {"材料": "地基为细砂"}, "摩擦系数", 0.5,
     "地基为细砂—粗砂 → f=0.50~0.60 取首数 0.50（下限，既有口径）",
     None, "fixed", "锁住范围文本取值口径（_extract_first_number 取下限）"),

    ("E11-子表头行适配", "table-doc-fbb3306e:23:10", "table_lookup", "子表头行在body[0]", "表4.3.7",
     {"护面型式": "四脚空心方块", "构造型式": "规则安放1层"}, "K_D", 14,
     "四脚空心方块×规则安放1层 → K_D=14（规范表4.3.7；SOP db749895 step_2 口径）",
     None, "fixed", "2026-10-18：子表头行在 body[0]（引擎不合并），SOP 改用 header 可见键「护面型式」"
     "过滤第 1 列 + 「构造型式」走行文本条件；含数字文本值（'规则安放1层'）修复了误判数值条件"),

    ("E12-子表头行适配-块石安放", "table-doc-fbb3306e:23:10", "table_lookup", "子表头行在body[0]", "表4.3.7",
     {"护面型式": "块石", "构造型式": "安放1层"}, "K_D", 5.5,
     "块石×安放1层 → K_D=5.5（同表第2行；修复前同过滤命中两行块石靠行序侥幸）",
     None, "fixed", "行文本条件「安放1层」只命中所属行"),

    ("E13-子表头行适配-扭王字", "table-doc-fbb3306e:23:10", "table_lookup", "子表头行在body[0]", "表4.3.7",
     {"护面型式": "扭王字块体", "构造型式": "随机安放1层"}, "K_D", 15,
     "扭王字块体×随机安放1层 → K_D=15~18 取首数 15（表注②由设计人取定）",
     None, "fixed", "锁住区间文本取下限口径"),
]

store = docs_service._canonical_store_for(LIB)
tables_out = []
for tid, sigs, why in TABLES:
    doc_id = tid.split(":")[0].replace("table-", "")
    t = next((x for x in store.list_tables(doc_id, limit=500) if x.table_id == tid), None)
    if t is None:
        raise SystemExit(f"找不到 {tid}")
    tables_out.append({
        "table_id": tid, "doc_id": doc_id, "page": t.page_start, "table_type": t.table_type,
        "title": t.title, "signatures": sigs, "why_picked": why,
        "header_rows": t.header_rows, "body_rows": t.body_rows,
    })

# 确定性通道基线实跑（覆盖 baseline=None 的 lookup 用例）
cands = [{"header_rows": t["header_rows"], "rows": t["body_rows"], "context": t["title"],
          "doc_id": t["doc_id"], "page_idx": t["page"], "library_id": LIB, "table_id": t["table_id"]}
         for t in tables_out]
cases_out = []
for (cid, tid, chan, sig, tname, conds, target, exp, why, base, status, note) in CASES:
    base_val = base
    if chan == "table_lookup":
        out = query_tables(cands, table_name=tname, query_conditions=conds, target_column=target)
        base_val = out.get("result")
        base_mode = "error" if out.get("error") else "value"
    else:
        base_mode = "value"
    cases_out.append({
        "case_id": cid, "table_id": tid, "channel": chan, "signature": sig,
        "table_name": tname, "conditions": conds, "target_column": target,
        "expected": exp, "expected_why": why,
        "baseline": base_val, "baseline_mode": base_mode, "status": status, "note": note,
    })

fixture = {
    "meta": {
        "name": "table_type_regression", "version": "v1",
        "created": datetime.date.today().isoformat(),
        "corpus": "std-water 库（groups/standards.sqlite）；主体 doc-11922bab = JTS 165-2013 海港总体设计规范",
        "why": "P2 表格簇（P2-1 复式表头 / P2-2 成对列与别名 / P2-3 target 失配 / P2-7 区间列）的预注册回归集："
               "把三条改动的行为锁在真表快照上，先写死期望值与修复前基线，再动手改引擎。",
        "how": "生成器 services/angineer-core/tests/fixtures/build_table_type_regression.py（需本地语料）。tables=真表快照（离线、无语料依赖）；cases.expected=人工按快照核对出的真值；"
               "cases.baseline=2026-10-16 修复前实测（确定性通道实跑；读表通道取实况读数）。"
               "status=fixed 锁正确行为、xfail 记已知缺陷（修好后须改 fixed）。"
               "table_read 用例离线只断选表，取值断言需 P2_FIXTURE_LIVE=1（真 LLM，2026-10-16 首测：7 条 6 达标）。",
        "drift": "语料重解析后快照可能过期：python services/angineer-core/tests/fixtures/check_table_type_regression_drift.py 逐表对账。",
    },
    "tables": tables_out,
    "cases": cases_out,
}

os.makedirs(os.path.dirname(OUT), exist_ok=True)
with open(OUT, "w", encoding="utf-8", newline="\n") as f:
    json.dump(fixture, f, ensure_ascii=False, indent=2)
    f.write("\n")
print("written:", OUT, os.path.getsize(OUT), "bytes")
print("tables:", len(tables_out), "| cases:", len(cases_out),
      "| fixed:", sum(1 for c in cases_out if c["status"] == "fixed"),
      "| xfail:", sum(1 for c in cases_out if c["status"] == "xfail"),
      "| probe:", sum(1 for c in cases_out if c["status"] == "probe"))
for c in cases_out:
    mark = {"fixed": "✓", "xfail": "✗", "probe": "?"}[c["status"]]
    print(f"  {mark} {c['case_id']:22s} expected={str(c['expected'])[:24]:26s} baseline={str(c['baseline'])[:60]}")

# MinerU-Popo 管线图解

> 来源: `services/docs-core/src/popo` (submodule, commit 97d5601)
> 接线层: `services/docs-core/src/docs_core/read/popo_pipeline.py`

## 1. PoPo 整体管线

```mermaid
flowchart LR
    subgraph INPUT["输入 (MinerU 原始解析)"]
        A1["middle.json<br/>layout_dets + page_info"]
        A2["content_list.json<br/>(备选)"]
        A3["PDF 源文件<br/>mineru_render.pdf"]
    end

    A1 --> B["label_normalization.py<br/>Step 1: 标签归一化"]
    A2 --> B
    A3 -.按页截图给模型看.-> D

    B --> C["normalized/*.json<br/>pages 结构<br/>bbox → 0..1"]
    C --> D["run_inference.py<br/>Step 2: 云端 4B 模型推理"]
    D --> E["enriched/*.json<br/>语义块数组"]
    E --> F["get_json_tree.py<br/>Step 3: 构建文档树"]
    F --> G["document_tree.json<br/>树结构"]

    G --> H["popo_mapper.py<br/>映射"]
    H --> I["CanonicalBlock + OutlineNode"]
    I --> J["structure 阶段（统一结构化者）<br/>builder + write/projection.py 统一写出口"]
    J --> K["content.md<br/>doc_blocks_graph.jsonl/meta<br/>segments / base_rows+derived_rows"]
```

## 2. 数据流转 + 各层 Schema（字段视图）

```mermaid
flowchart TB
    subgraph L1["① 输入层: middle.json"]
        M1["每一页一个对象"]
        M1 --> M1a["page_info<br/>└ width, height"]
        M1 --> M1b["layout_dets[]<br/>└ bbox [x0,y0,x1,y1] (像素)<br/>└ block_label<br/>└ text"]
    end

    L1 -->|"归一化 + bbox→1000刻度→0..1"| L2

    subgraph L2["② 归一化层: normalized/<doc_id>.json"]
        N1["顶层<br/>model, doc_id, input_label(指向PDF)"]
        N1 --> N2["pages{}<br/>页号 → 块列表"]
        N2 --> N3["每个块:<br/>type(16种之一)<br/>content<br/>bbox[0..1]<br/>title_level?<br/>source_label?<br/>source_id"]
    end

    L2 -->|"推理: 截断/标题层级/图文关联/跨页表格"| L3

    subgraph L3["③ 推理层: enriched_blocks.json"]
        E1["doc_blocks[]"]
        E1 --> E2["每个块:<br/>id(重编号)<br/>page, type, content, bbox<br/>contd: 续接块id / -1<br/>level: 标题层级 / -1<br/>image: 关联图片id / -1<br/>table_merge?: 配对表id<br/>cell_list?"]
    end

    L3 -->|"构建树 + 跨页表格合并"| L4

    subgraph L4["④ 文档树: document_tree.json"]
        T1["root"]
        T1 --> T2["text 组件<br/>title=所属标题<br/>content=多块拼接<br/>(<|txt_split|>/<|txt_contd|>)<br/>location[{bbox,page}]*<br/>block_ids[]"]
        T1 --> T3["table/chart/image 组件<br/>title=合并caption<br/>metadata=合并footnote<br/>content=HTML<br/>block_ids=跨页合并集"]
        T1 --> T4["supplement 组件<br/>page_number/header/footer/...<br/>title=Page N - 类型"]
        T2 --> T5["children 递归嵌套<br/>(按标题层级)"]
    end

    L4 -->|"映射"| L5

    subgraph L5["⑤ 内部统一层: CanonicalBlock"]
        C1["block_id=b12<br/>block_type(10种)<br/>text, text_clean<br/>page_idx, reading_order<br/>title_level?<br/>section_path=第一节/1.1<br/>parent_block_id?<br/>contd_target_id?<br/>image_assoc_id?<br/>table_merge_id?<br/>source=mineru-popo"]
    end

    L5 -->|"统一写出口<br/>(write/projection.py)"| L6

    subgraph L6["⑥ 下游产物层"]
        P1["content.md<br/>(按块顺序重建)"]
        P2["doc_blocks_graph.jsonl/meta<br/>nodes + edges(parent/contd/<br/>table_merge/before)"]
        P3["document_segments[]<br/>+ base_rows[]"]
    end
```

## 3. 类型映射图（PoPo 16 种 → Canonical 10 种）

```mermaid
flowchart LR
    subgraph POPO["PoPo 类型"]
        A1["title"]
        A2["text"]
        A3["list_item"]
        A4["equation"]
        A5["image"]
        A6["table"]
        A7["image_caption"]
        A8["table_caption"]
        A9["image_footnote<br/>table_footnote"]
        A10["page_title<br/>page_number<br/>page_footnote<br/>header<br/>footer"]
        A11["aside_text"]
    end

    subgraph CANON["Canonical block_type"]
        B1["title"]
        B2["paragraph"]
        B3["list_item"]
        B4["formula"]
        B5["figure"]
        B6["table"]
        B7["figure_caption"]
        B8["table_caption"]
        B9["footnote"]
        B10["header_footer"]
    end

    A1 --> B1
    A2 --> B2
    A3 --> B3
    A4 --> B4
    A5 --> B5
    A6 --> B6
    A7 --> B7
    A8 --> B8
    A9 --> B9
    A10 --> B10
    A11 --> B2
```

## 4. 文档树结构示意（实例）

```mermaid
flowchart TD
    ROOT["root (level 0)"]

    ROOT --> S1["text 组件<br/>title: 第一章 绪论 | level 1<br/>block_ids: [1,2,3]"]
    ROOT --> S2["text 组件<br/>title: 1.1 背景 | level 2<br/>block_ids: [4,5]"]
    ROOT --> S3["table 组件<br/>title: 表1 数据汇总<br/>metadata: 注:单位万元<br/>block_ids: [30,31]<br/>(跨页合并)"]
    ROOT --> S4["page_footnote<br/>title: Page 3 - page_footnote"]
    ROOT --> S5["text 组件<br/>title: 1.2 方法 | level 2<br/>block_ids: [7,8]"]

    S2 --> S3
    S5 --> S6["image 组件<br/>title: 图1 流程<br/>block_ids: [12]"]
```

## 要点

- **输入是页面级布局 → 归一化 → 模型推理出语义 → 树 → 映射成内部统一块（CanonicalBlock）→ structure 阶段统一写出口生成下游产物**
- 中间任何一层都只是数据格式转换，不改语义
- 跨页表格合并发生在第 ④ 层之前（`merge_cross_page_tables`，commit 97d5601 修复）
- popo 不再经 `popo_projection.py`（阶段三已删除）：graph/segments/base_rows 由 `write/projection.py` 从 CanonicalDocument 统一生成，表格 HTML/math_content 经 derived_rows 落库

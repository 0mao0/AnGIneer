"""Phase 0 测试共享 fixture：伪造 popo enriched_blocks 输入。"""

EMPTY_TREE = {"type": "root", "children": []}

TABLE_HTML = (
    "<table><tr><td>参数</td><td>数值</td></tr>"
    "<tr><td>高度</td><td>100</td></tr></table>"
)

MERGED_TABLE_HTML = (
    "<table><tr><th colspan=\"2\">参数</th><th>数值</th></tr>"
    "<tr><td>高度</td><td>H</td><td>100</td></tr>"
    "<tr><td>宽度</td><td>B</td><td>200</td></tr>"
    "<tr><td>深度</td><td>D</td><td>300</td></tr></table>"
)


def make_block(
    block_id: int,
    page: int,
    block_type: str,
    content: str,
    *,
    level: int = -1,
    image: int = -1,
    table_merge: int = -1,
    contd: int = -1,
    cell_list: list = None,
) -> dict:
    payload = {
        "id": block_id,
        "page": page,
        "type": block_type,
        "content": content,
        "bbox": [0.0, 0.0, 100.0, 50.0],
        "level": level,
        "image": image,
        "table_merge": table_merge,
        "contd": contd,
    }
    if cell_list is not None:
        payload["cell_list"] = cell_list
    return payload


def build_noise_fixture() -> list[dict]:
    """含各类噪声块的 popo enriched_blocks 样本。"""
    blocks = [
        make_block(1, 1, "title", "第一章 总则", level=1),
        make_block(2, 1, "text", "这是正文段落。"),
        make_block(3, 1, "page_number", "12"),
        make_block(4, 1, "page_title", "某工程标准"),
        make_block(5, 1, "header", "页眉文本"),
        make_block(6, 1, "footer", "第 1 页 共 3 页"),
        make_block(7, 1, "page_footnote", "页脚注释"),
        make_block(8, 2, "page_number", "13"),
        make_block(9, 1, "aside_text", "旁注：本页内容依据勘误表修改"),
        make_block(10, 1, "image", "", image=-1),
        make_block(11, 1, "image_caption", "图 1 结构示意", image=10),
        make_block(12, 1, "image_footnote", "注：示意图来源自测", image=10),
        make_block(13, 2, "table", TABLE_HTML, table_merge=-1),
        make_block(14, 2, "table_caption", "表 1 参数表", table_merge=13),
        make_block(15, 2, "table_footnote", "注：单位 kN", table_merge=13),
    ]
    return blocks


def build_clean_fixture() -> list[dict]:
    """无噪声块的 popo enriched_blocks 样本。"""
    return [
        make_block(1, 1, "title", "第一章 总则", level=1),
        make_block(2, 1, "text", "这是正文段落。"),
        make_block(3, 2, "equation", "F = ma"),
        make_block(4, 2, "text", "式中：F 为合力。"),
    ]


def build_table_fixture() -> list[dict]:
    """含跨页合并表格（多数据行 + colspan + cell_list）的 popo enriched_blocks 样本。"""
    return [
        make_block(1, 1, "title", "第五章 构件", level=1),
        make_block(2, 2, "table", MERGED_TABLE_HTML, table_merge=-1, cell_list=[0, 1, 0]),
        make_block(3, 2, "table_caption", "表 5.2-1 构件尺寸参数", table_merge=2),
        make_block(4, 2, "table_footnote", "注：单位 mm", table_merge=2),
    ]

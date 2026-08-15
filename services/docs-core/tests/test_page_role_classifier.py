from docs_core.step04_structure.shared.page_role_classifier import (
    classify_page_roles, DocumentPart, PageRole,
)

def _row(page_idx, text, block_type="paragraph", id_=0):
    return {
        "id": id_, "page_idx": page_idx, "block_type": block_type,
        "plain_text": text,
        "content_json": {"level": None},
    }

def _rows():
    return [
        _row(0, "船闸闸阀门设计规范", "title", 1),          # 封面
        _row(0, "中华人民共和国交通部发布", "paragraph", 2),
        _row(1, "主编单位：四川省交通厅内河勘察规划设计院", "paragraph", 3),  # 副页
        _row(2, "关于发布《船闸闸阀门设计规范》的通知", "title", 4),          # 通知
        _row(3, "修订说明", "title", 5),                     # 修订说明
        _row(5, "目次", "title", 6),                         # 目次
        _row(8, "2 基本规定", "title", 7),                   # 正文起始
        _row(8, "2.1 一般规定", "title", 8),
        _row(20, "附录 A 术语", "title", 9),                 # 附录
    ]

def test_body_start_is_first_numbered_title_page():
    roles = classify_page_roles(_rows())
    assert roles[8] == PageRole.BODY
    assert roles[0] != PageRole.BODY

def test_front_matter_roles_by_keyword():
    roles = classify_page_roles(_rows())
    assert roles[0] == PageRole.COVER
    assert roles[1] == PageRole.PUBLICATION_PAGE
    assert roles[2] == PageRole.NOTICE
    assert roles[3] == PageRole.REVISION_NOTES
    assert roles[5] == PageRole.TOC

def test_part_mapping():
    from docs_core.step04_structure.shared.page_role_classifier import part_for_role
    assert part_for_role(PageRole.REVISION_NOTES) == DocumentPart.FRONT_MATTER
    assert part_for_role(PageRole.BODY) == DocumentPart.BODY
    assert part_for_role(PageRole.APPENDIX) == DocumentPart.APPENDIX


def test_body_page_with_appendix_cross_reference_stays_body():
    rows = [
        _row(8, "2 基本规定", "title", 1),
        _row(8, "构件计算可参照附录 D 的有关规定进行。", "paragraph", 2),
        _row(8, "2.1 一般规定", "title", 3),
    ]
    roles = classify_page_roles(rows)
    assert roles[8] == PageRole.BODY


def test_appendix_title_page_is_appendix():
    rows = [
        _row(8, "2 基本规定", "title", 1),
        _row(20, "附录 A 术语", "title", 2),
    ]
    roles = classify_page_roles(rows)
    assert roles[20] == PageRole.APPENDIX


def test_appendix_only_document_all_pages_appendix():
    """无数字编号正文的纯附录文档，不应落入封面/未知前置页。"""
    rows = [
        _row(0, "附录 A 设计船型尺度及其他参数", "title", 1),
        _row(0, "A.0.1 设计船型及其尺度应通过分析论证确定。", "paragraph", 2),
        _row(1, "续表 A.0.2-2", "paragraph", 3),
        _row(1, "表 A.0.2-3 油船设计船型尺度", "table", 4),
        _row(2, "", "page_header", 5),
    ]
    roles = classify_page_roles(rows)
    assert roles[0] == PageRole.APPENDIX
    assert roles[1] == PageRole.APPENDIX
    assert roles[2] == PageRole.APPENDIX


def test_continuation_pages_inherit_body_appendix_backmatter_part():
    """正文/附录/后记的续页无标题时应继承当前部位，而不是退回 body。"""
    rows = [
        _row(8, "2 基本规定", "title", 1),
        _row(9, "正文续页无标题", "paragraph", 2),
        _row(20, "附录 A 术语", "title", 3),
        _row(21, "续表 A", "paragraph", 4),
        _row(30, "用词说明", "title", 5),
        _row(31, "用词说明续页", "paragraph", 6),
    ]
    roles = classify_page_roles(rows)
    assert roles[8] == PageRole.BODY
    assert roles[9] == PageRole.BODY
    assert roles[20] == PageRole.APPENDIX
    assert roles[21] == PageRole.APPENDIX
    assert roles[30] == PageRole.BACK_MATTER
    assert roles[31] == PageRole.BACK_MATTER


def test_body_page_with_back_matter_cross_reference_stays_body():
    rows = [
        _row(8, "2 基本规定", "title", 1),
        _row(8, "详见条文说明。", "paragraph", 2),
        _row(9, "本标准用词说明", "title", 3),
    ]
    roles = classify_page_roles(rows)
    assert roles[8] == PageRole.BODY
    assert roles[9] == PageRole.BACK_MATTER


def test_furniture_text_ignored_for_page_role():
    rows = [
        _row(8, "2 基本规定", "title", 1),
        _row(8, "详见条文说明。", "page_footer", 2),
        _row(9, "本标准用词说明", "title", 3),
    ]
    roles = classify_page_roles(rows)
    assert roles[8] == PageRole.BODY
    assert roles[9] == PageRole.BACK_MATTER


def test_furniture_keyword_text_does_not_change_page_role():
    rows = [
        _row(0, "船闸闸阀门设计规范", "title", 1),
        _row(0, "目次", "page_footer", 2),
    ]
    roles = classify_page_roles(rows)
    assert roles[0] == PageRole.COVER


def test_page_role_enum_has_furniture_roles():
    assert PageRole.PAGE_HEADER.value == "page_header"
    assert PageRole.PAGE_FOOTER.value == "page_footer"
    assert PageRole.PAGE_NUMBER.value == "page_number"


def test_page_role_for_block_uses_furniture_role():
    from docs_core.step04_structure.shared.page_role_classifier import page_role_for_block
    assert page_role_for_block("page_footer", PageRole.BODY) == PageRole.PAGE_FOOTER
    assert page_role_for_block("paragraph", PageRole.BODY) == PageRole.BODY


def test_table_continuation_header_is_content_not_furniture():
    from docs_core.step04_structure.shared.page_role_classifier import (
        is_page_furniture, is_table_continuation_header, page_role_for_block,
    )
    assert is_table_continuation_header("page_header", "续表 A.0.2-3")
    assert not is_table_continuation_header("page_header", "免费标准下载网")
    assert not is_page_furniture("page_header", "续表 A.0.2-3")
    assert is_page_furniture("page_header", "免费标准下载网")
    assert page_role_for_block(
        "page_header", PageRole.BODY, "续表 A.0.2-3"
    ) == PageRole.TABLE_CONTINUATION


def test_unknown_page_document_part_fallback():
    from docs_core.step04_structure.shared.page_role_classifier import resolve_document_part
    assert resolve_document_part(4, PageRole.UNKNOWN, 8) == DocumentPart.FRONT_MATTER
    assert resolve_document_part(10, PageRole.UNKNOWN, 8) == DocumentPart.BODY
    assert resolve_document_part(3, PageRole.REVISION_NOTES, 8) == DocumentPart.FRONT_MATTER

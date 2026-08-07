"""页面角色规则分类：page_idx -> PageRole，并映射 document_part。"""
import re
from enum import Enum
from typing import Any, Dict, List


class DocumentPart(str, Enum):
    FRONT_MATTER = "front_matter"
    BODY = "body"
    APPENDIX = "appendix"
    BACK_MATTER = "back_matter"
    UNKNOWN = "unknown"


class PageRole(str, Enum):
    COVER = "cover"
    PUBLICATION_PAGE = "publication_page"
    NOTICE = "notice"
    REVISION_NOTES = "revision_notes"
    TOC = "toc"
    PREFACE = "preface"
    BODY = "body"
    APPENDIX = "appendix"
    BACK_MATTER = "back_matter"
    UNKNOWN = "unknown"
    PAGE_HEADER = "page_header"
    PAGE_FOOTER = "page_footer"
    PAGE_NUMBER = "page_number"
    HEADER = "header"
    FOOTER = "footer"


PART_BY_ROLE = {
    PageRole.COVER: DocumentPart.FRONT_MATTER,
    PageRole.PUBLICATION_PAGE: DocumentPart.FRONT_MATTER,
    PageRole.NOTICE: DocumentPart.FRONT_MATTER,
    PageRole.REVISION_NOTES: DocumentPart.FRONT_MATTER,
    PageRole.TOC: DocumentPart.FRONT_MATTER,
    PageRole.PREFACE: DocumentPart.FRONT_MATTER,
    PageRole.BODY: DocumentPart.BODY,
    PageRole.APPENDIX: DocumentPart.APPENDIX,
    PageRole.BACK_MATTER: DocumentPart.BACK_MATTER,
    PageRole.UNKNOWN: DocumentPart.UNKNOWN,
}

_NUMBERED_TITLE_RE = re.compile(r"^\d+(?:\.\d+)*\s")
_TOC_KEYWORDS = ("目次", "目录")
_NOTICE_KEYWORDS = ("关于发布",)
_REVISION_KEYWORDS = ("修订说明",)
_PUBLICATION_KEYWORDS = ("主编单位", "批准部门", "施行日期")
_PREFACE_KEYWORDS = ("前言", "编制说明")
_BACK_MATTER_KEYWORDS = ("用词说明", "条文说明")

FURNITURE_BLOCK_TYPES = frozenset({
    "page_header", "page_footer", "page_number", "header", "footer",
})

FURNITURE_ROLE_BY_TYPE = {
    "page_header": PageRole.PAGE_HEADER,
    "page_footer": PageRole.PAGE_FOOTER,
    "page_number": PageRole.PAGE_NUMBER,
    "header": PageRole.HEADER,
    "footer": PageRole.FOOTER,
}


def part_for_role(role: PageRole) -> DocumentPart:
    return PART_BY_ROLE.get(role, DocumentPart.UNKNOWN)


def is_furniture_block_type(block_type: Any) -> bool:
    return str(block_type or "").strip().lower() in FURNITURE_BLOCK_TYPES


def page_role_for_block(block_type: Any, page_role: PageRole) -> PageRole:
    """内容块返回页面角色；页饰块返回自身小角色。"""
    if is_furniture_block_type(block_type):
        return FURNITURE_ROLE_BY_TYPE.get(
            str(block_type or "").strip().lower(), PageRole.UNKNOWN
        )
    return page_role


def _page_text(rows: List[Dict[str, Any]], page_idx: int) -> str:
    return " ".join(
        str(r.get("plain_text") or "")
        for r in rows
        if int(r.get("page_idx") or 0) == page_idx
        and not is_furniture_block_type(r.get("block_type"))
    )


def _detect_body_start(rows: List[Dict[str, Any]], toc_pages) -> int:
    """正文起始页 = 第一个非 toc 页上出现编号标题的页。"""
    for page_idx in sorted({int(r.get("page_idx") or 0) for r in rows}):
        if page_idx in toc_pages:
            continue
        for r in rows:
            if int(r.get("page_idx") or 0) != page_idx:
                continue
            if str(r.get("block_type") or "") == "title" and _NUMBERED_TITLE_RE.match(
                str(r.get("plain_text") or "")
            ):
                return page_idx
    return max((int(r.get("page_idx") or 0) for r in rows), default=0) + 1


def _classify_front_page(page_idx: int, text: str, is_first: bool) -> PageRole:
    if any(k in text for k in _REVISION_KEYWORDS):
        return PageRole.REVISION_NOTES
    if any(k in text for k in _TOC_KEYWORDS):
        return PageRole.TOC
    if any(k in text for k in _NOTICE_KEYWORDS):
        return PageRole.NOTICE
    if any(k in text for k in _PUBLICATION_KEYWORDS):
        return PageRole.PUBLICATION_PAGE
    if any(k in text for k in _PREFACE_KEYWORDS):
        return PageRole.PREFACE
    if is_first:
        return PageRole.COVER
    return PageRole.UNKNOWN


def _page_title_compacts(rows: List[Dict[str, Any]], page_idx: int) -> List[str]:
    """该页 title 块文本（去空白）。"""
    return [
        re.sub(r"\s+", "", str(r.get("plain_text") or ""))
        for r in rows
        if int(r.get("page_idx") or 0) == page_idx
        and str(r.get("block_type") or "") == "title"
    ]


def _page_has_appendix_title(rows: List[Dict[str, Any]], page_idx: int) -> bool:
    """附录页判定：仅当页面标题行以“附录”开头，避免正文交叉引用误判。"""
    return any(text.startswith("附录") for text in _page_title_compacts(rows, page_idx))


def _page_has_back_matter_title(rows: List[Dict[str, Any]], page_idx: int) -> bool:
    """后记页判定：仅当标题行包含用词说明/条文说明等关键词。"""
    return any(
        any(k in text for k in _BACK_MATTER_KEYWORDS)
        for text in _page_title_compacts(rows, page_idx)
    )


def detect_body_start_page(rows: List[Dict[str, Any]], toc_pages=None) -> int:
    return _detect_body_start(rows, set(toc_pages or []))


def resolve_document_part(
    page_idx: int, role: PageRole, body_start: int
) -> DocumentPart:
    """未知角色页按位置兜底：body_start 前为 front_matter，之后为 body。"""
    if role != PageRole.UNKNOWN:
        return part_for_role(role)
    return DocumentPart.FRONT_MATTER if page_idx < body_start else DocumentPart.BODY


def classify_page_roles(rows: List[Dict[str, Any]], toc_pages=None) -> Dict[int, PageRole]:
    """返回 {page_idx: PageRole}。规则基线：正文起始页之前为 front_matter。"""
    toc_pages = set(toc_pages or [])
    body_start = _detect_body_start(rows, toc_pages)
    pages = sorted({int(r.get("page_idx") or 0) for r in rows})
    roles: Dict[int, PageRole] = {}
    for page_idx in pages:
        text = _page_text(rows, page_idx)
        if page_idx in toc_pages or any(k in text for k in _TOC_KEYWORDS):
            roles[page_idx] = PageRole.TOC
        elif page_idx >= body_start:
            if _page_has_appendix_title(rows, page_idx):
                roles[page_idx] = PageRole.APPENDIX
            elif _page_has_back_matter_title(rows, page_idx):
                roles[page_idx] = PageRole.BACK_MATTER
            else:
                roles[page_idx] = PageRole.BODY
        else:
            roles[page_idx] = _classify_front_page(
                page_idx, text, is_first=(page_idx == pages[0])
            )
    return roles


__all__ = [
    "DocumentPart", "PageRole", "PART_BY_ROLE", "part_for_role",
    "FURNITURE_BLOCK_TYPES", "is_furniture_block_type", "page_role_for_block",
    "detect_body_start_page", "resolve_document_part",
    "classify_page_roles",
]

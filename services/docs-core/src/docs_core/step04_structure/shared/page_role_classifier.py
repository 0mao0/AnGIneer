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
_APPENDIX_KEYWORDS = ("附录",)
_BACK_MATTER_KEYWORDS = ("用词说明", "条文说明")


def part_for_role(role: PageRole) -> DocumentPart:
    return PART_BY_ROLE.get(role, DocumentPart.UNKNOWN)


def _page_text(rows: List[Dict[str, Any]], page_idx: int) -> str:
    return " ".join(
        str(r.get("plain_text") or "")
        for r in rows if int(r.get("page_idx") or 0) == page_idx
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
            if any(k in text for k in _APPENDIX_KEYWORDS):
                roles[page_idx] = PageRole.APPENDIX
            elif any(k in text for k in _BACK_MATTER_KEYWORDS):
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
    "classify_page_roles",
]

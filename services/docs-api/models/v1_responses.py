"""v1 API 统一响应模型。"""
from typing import Optional, Any, List
from pydantic import BaseModel, Field


class ErrorDetail(BaseModel):
    code: str = Field(..., example="INVALID_KEY")
    message: str = Field(..., example="API key is invalid or expired")


class ErrorResponse(BaseModel):
    error: ErrorDetail


class PaginationMeta(BaseModel):
    page: int = 1
    page_size: int = 100
    total: int = 0


class ParseResponse(BaseModel):
    doc_id: str = Field(..., example="abc123")
    task_id: str = Field(..., example="task_xyz")
    status: str = Field("queued", example="queued")
    is_pdf_input: bool = Field(..., description="若为 True，用户已有原始 PDF；False 则需要从 API 下载 PDF")


class ParseStatusResponse(BaseModel):
    doc_id: str
    status: str = Field(..., example="processing")
    progress: int = Field(0, example=45)
    stage: str = Field("", example="raw_parse")
    stage_message: str = Field("", example="MinerU 原始结果下载中")
    pdf_ready: bool = Field(False)
    error: Optional[str] = Field(None)


class Block(BaseModel):
    block_id: str
    block_type: str = Field(..., example="paragraph")
    page_idx: int = Field(0)
    block_seq: int = Field(0)
    text: str = ""
    bbox: Optional[List[float]] = Field(None, example=[0.12, 0.35, 0.88, 0.42])
    heading_level: Optional[int] = Field(None)
    section_path: Optional[str] = Field(None, example="第5章 > 5.2 材料要求")
    parent_block_id: Optional[str] = Field(None)
    children: List[str] = Field(default_factory=list)
    image_url: Optional[str] = Field(None)
    table_html: Optional[str] = Field(None)
    math_latex: Optional[str] = Field(None)


class OutlineItem(BaseModel):
    level: int
    title: str
    page_idx: int
    block_ids: List[str] = Field(default_factory=list)


class BlocksResponse(BaseModel):
    doc_id: str
    filename: str
    page_count: int = 0
    blocks: List[Block] = Field(default_factory=list)
    outline: List[OutlineItem] = Field(default_factory=list)
    pagination: Optional[PaginationMeta] = None


class ContentResponse(BaseModel):
    doc_id: str
    markdown: str


class ArtifactListItem(BaseModel):
    name: str
    kind: str = Field(..., description="markdown / images / structure / index / graph")
    size: Optional[int] = None
    url: str


class ArtifactsResponse(BaseModel):
    doc_id: str
    items: List[ArtifactListItem] = Field(default_factory=list)


class MeResponse(BaseModel):
    key_prefix: str = Field(..., example="ag_****a1b2")
    user_name: str
    email: str
    rate_limit_per_minute: int
    created_at: str
    # 租户绑定库（P2）：'' = 未绑定（旧 key，需管理员绑定后才有隔离）
    library_id: str = ""
    library_exists: bool = False


class CreateKeyRequest(BaseModel):
    user_name: str = Field(..., min_length=1, max_length=100)
    scope: str = Field(default="both", pattern="^(doc|chat|both)$")
    library_id: str = Field(..., min_length=1, description="绑定的知识库 ID（必选，key 只能访问此库）")


class CreateKeyResponse(BaseModel):
    api_key: str = Field(..., description="完整 key，仅此时可见")
    key_prefix: str
    user_name: str
    created_at: str
    message: str = Field("请妥善保管此 Key，离开此页面后将无法再次查看完整 Key。")


class KeyListItem(BaseModel):
    id: int
    key_prefix: str
    user_name: str
    email: str
    is_active: bool
    rate_limit_per_minute: int
    created_at: str
    last_used_at: Optional[str] = None

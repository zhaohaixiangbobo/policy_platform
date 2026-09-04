"""文件说明：定义active制度目录、详情和Node公开契约。"""

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class DocumentSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    document_code: str | None
    issuer: str | None
    responsibility_department: str | None
    status: str
    publish_date: date | None
    effective_date: date | None
    active_parse_run_id: int
    has_pdf: bool
    updated_at: datetime


class DocumentListResponse(BaseModel):
    items: list[DocumentSummary]
    total: int
    page: int
    page_size: int


class DocumentFacetsResponse(BaseModel):
    """制度列表真实可用的筛选候选值。"""

    statuses: list[str]
    issuers: list[str]
    departments: list[str]


class DocumentDetail(DocumentSummary):
    """active制度详情；详细字段与列表摘要保持一致。"""


class DocumentTableCell(BaseModel):
    """Parser 从 OOXML 保存的真实表格单元格结构。"""

    row: int = Field(ge=0)
    column: int = Field(ge=0)
    text: str
    grid_span: int = Field(default=1, ge=1)
    vertical_merge: Literal["restart", "continue"] | None = None


class DocumentTableStructure(BaseModel):
    """Reading View 使用的表格行列与合并信息。"""

    rows: list[list[DocumentTableCell]]
    row_count: int = Field(ge=0)
    cell_count: int = Field(ge=0)


class DocumentNode(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    document_id: int
    parse_run_id: int
    parent_id: int | None
    node_type: str
    node_number: str | None
    title: str | None
    text: str
    path_text: str | None
    order_no: int
    page_start: int | None
    page_end: int | None
    table_structure: DocumentTableStructure | None = None


class DocumentNodeListResponse(BaseModel):
    document_id: int
    active_parse_run_id: int
    items: list[DocumentNode]

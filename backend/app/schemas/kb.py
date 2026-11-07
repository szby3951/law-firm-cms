"""知识库相关的请求/响应模型（模块 9.1）。

只覆盖「知识库构建与检索」这一层：法条清单、律所知识增删改、语义检索结果、
知识库概览。9.3 的问答会话在 ``schemas/ai.py`` 中另建。
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, computed_field, field_validator

KB_CATEGORIES = ("faq", "case_summary", "manual")

KB_CATEGORY_LABELS = {
    "faq": "常见问题",
    "case_summary": "案件摘要",
    "manual": "办案手册",
}

KB_SOURCES = ("law", "firm")


class LawArticleOut(BaseModel):
    """一条法条（列表用，不含长正文）。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    law_name: str
    chapter: str | None = None
    article_no: str
    content: str
    effective_status: str
    vector_id: str | None = None


class KbDocumentCreate(BaseModel):
    """新增律所知识。"""

    title: str = Field(min_length=2, max_length=255, description="标题")
    category: Literal["faq", "case_summary", "manual"] = Field(
        default="faq", description="分类"
    )
    content: str = Field(min_length=10, max_length=20000, description="正文")

    @field_validator("title", "content")
    @classmethod
    def _strip(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("不能为空")
        return v


class KbDocumentUpdate(BaseModel):
    """修改律所知识（正文变更会触发重新向量化）。"""

    title: str | None = Field(default=None, min_length=2, max_length=255)
    category: Literal["faq", "case_summary", "manual"] | None = None
    content: str | None = Field(default=None, min_length=10, max_length=20000)

    @field_validator("title", "content")
    @classmethod
    def _strip(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = v.strip()
        if not v:
            raise ValueError("不能为空")
        return v


class KbDocumentOut(BaseModel):
    """律所知识输出。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    category: str
    content: str
    vector_id: str | None = None
    created_by: int | None = None
    created_at: datetime

    @computed_field  # type: ignore[prop-decorator]
    @property
    def category_label(self) -> str:
        return KB_CATEGORY_LABELS.get(self.category, self.category)


class KbDocumentListOut(BaseModel):
    """分页列表。"""

    total: int
    items: list[KbDocumentOut]


class KbSearchIn(BaseModel):
    """语义检索请求。"""

    query: str = Field(min_length=1, max_length=500, description="检索内容")
    top_k: int = Field(default=6, ge=1, le=50, description="返回条数")
    source: Literal["law", "firm"] | None = Field(
        default=None, description="只查法条 / 只查律所知识"
    )
    min_score: float | None = Field(default=None, ge=0, le=1, description="相似度下限")


class KbHit(BaseModel):
    """一条检索结果。"""

    score: float
    source: str
    content: str
    point_id: str | None = None
    # 法条命中时
    article_id: int | None = None
    law_name: str | None = None
    chapter: str | None = None
    article_no: str | None = None
    effective_status: str | None = None
    # 律所知识命中时
    kb_id: int | None = None
    title: str | None = None
    category: str | None = None
    chunk_index: int = 0
    chunk_count: int = 1


class KbSearchOut(BaseModel):
    """检索结果集。"""

    query: str
    count: int
    items: list[KbHit]


class KbStatsOut(BaseModel):
    """知识库概览：条数、向量数、服务健康度。"""

    law_total: int
    firm_total: int
    law_by_name: dict[str, int]
    firm_by_category: dict[str, int]
    vector_points: int
    collection: str
    embedding_model: str
    embedding_dim: int
    qdrant_ok: bool
    qdrant_error: str | None = None
    embedding_ok: bool
    embedding_error: str | None = None

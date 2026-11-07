"""文书管理相关的请求/响应模型。

覆盖：模板增改查、文书增改查、模板变量填充预览、docx 导出结果。
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, computed_field, field_validator

from app.services import dict_cache

# 文书类型（与 dict_item 中 doc_type 字典一致）
DOC_TYPES = (
    "complaint",
    "response",
    "agency_argument",
    "lawyer_letter",
    "opinion",
    "poa",
    "other",
)

DOC_TYPE_LABELS = {
    "complaint": "起诉状",
    "response": "答辩状",
    "agency_argument": "代理词",
    "lawyer_letter": "律师函",
    "opinion": "法律意见书",
    "poa": "委托书",
    "other": "其他文书",
}

# 文书状态：published 才在客户端可见
DOC_STATUSES = ("draft", "final", "published")
DOC_STATUS_LABELS = {
    "draft": "草稿",
    "final": "定稿",
    "published": "已发布",
}

# 模板可用的占位符清单（供前端「插入变量」下拉使用）
TEMPLATE_VARIABLES: tuple[dict[str, str], ...] = (
    {"key": "客户姓名", "desc": "委托客户姓名/机构名称"},
    {"key": "客户电话", "desc": "客户联系电话"},
    {"key": "客户地址", "desc": "客户联系地址"},
    {"key": "客户证件号", "desc": "客户身份证号/统一社会信用代码"},
    {"key": "客户性别", "desc": "客户性别（个人客户）"},
    {"key": "案号", "desc": "案件编号"},
    {"key": "案件标题", "desc": "案件标题"},
    {"key": "案由", "desc": "案件案由"},
    {"key": "受理法院", "desc": "受理法院/机构"},
    {"key": "对方当事人", "desc": "对方当事人"},
    {"key": "标的额", "desc": "案件标的额（元，带千分位）"},
    {"key": "委托律师", "desc": "承办律师姓名"},
    {"key": "律所名称", "desc": "律师事务所全称"},
    {"key": "律所地址", "desc": "律所地址"},
    {"key": "律所电话", "desc": "律所联系电话"},
    {"key": "今日日期", "desc": "生成当日（2026年11月4日）"},
    {"key": "年份", "desc": "当前年份"},
    {"key": "月份", "desc": "当前月份"},
    {"key": "日期", "desc": "当前日"},
)

# 正文最大长度：LONGTEXT 足够大，这里设一个上限防止误传超大文本
MAX_CONTENT_LENGTH = 1_000_000


def _check_doc_type(v: str | None) -> str | None:
    """文书类型必须在允许集合内。"""
    if v is None:
        return v
    if v not in DOC_TYPES:
        raise ValueError(f"文书类型不合法，可选：{'/'.join(DOC_TYPES)}")
    return v


class TemplateIn(BaseModel):
    """文书模板入参（新增/更新复用）。"""

    model_config = ConfigDict(str_strip_whitespace=True)

    doc_type: str = Field(description="文书类型")
    name: str = Field(min_length=1, max_length=128, description="模板名称")
    content: str = Field(
        min_length=1, max_length=MAX_CONTENT_LENGTH, description="模板正文，含 {变量}"
    )

    @field_validator("doc_type")
    @classmethod
    def _valid_doc_type(cls, v: str) -> str:
        _check_doc_type(v)
        return v

    @field_validator("name", "content")
    @classmethod
    def _not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("模板名称与正文不能为空")
        return v


class TemplateBriefOut(BaseModel):
    """模板列表项（不含完整正文，仅摘要）。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    doc_type: str
    name: str
    var_keys: list[str] = Field(default_factory=list, description="正文中的变量名")
    excerpt: str | None = Field(default=None, description="正文纯文本摘要")
    created_at: datetime
    updated_at: datetime

    @computed_field  # type: ignore[prop-decorator]
    @property
    def doc_type_label(self) -> str:
        """文书类型中文名：以管理端字典为准，内置常量仅作兜底。"""
        return dict_cache.label_of(
            "doc_type", self.doc_type, DOC_TYPE_LABELS.get(self.doc_type, self.doc_type)
        )


class TemplateOut(TemplateBriefOut):
    """模板详情：附完整正文。"""

    content: str


class TemplateListOut(BaseModel):
    """模板列表输出。"""

    total: int
    items: list[TemplateBriefOut]


class DocumentIn(BaseModel):
    """文书入参（新增/PUT 全量更新复用）。"""

    model_config = ConfigDict(str_strip_whitespace=True)

    title: str = Field(min_length=1, max_length=255, description="文书标题")
    doc_type: str | None = Field(default=None, description="文书类型")
    case_id: int | None = Field(default=None, description="关联案件ID")
    content: str | None = Field(
        default=None, max_length=MAX_CONTENT_LENGTH, description="富文本正文"
    )
    status: str = Field(
        default="draft",
        pattern="^(draft|final|published)$",
        description="状态：draft 草稿 / final 定稿 / published 客户可见",
    )
    is_ai_generated: bool = Field(default=False, description="是否 AI 生成")
    ai_session_id: int | None = Field(default=None, description="AI 会话ID")

    @field_validator("doc_type")
    @classmethod
    def _valid_doc_type(cls, v: str | None) -> str | None:
        return _check_doc_type(v)

    @field_validator("title")
    @classmethod
    def _title_not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("文书标题不能为空")
        return v


class DocumentFromTemplateIn(BaseModel):
    """按模板生成文书草稿的入参。"""

    template_id: int = Field(description="模板ID")
    case_id: int | None = Field(default=None, description="关联案件ID（用于取变量值）")
    title: str | None = Field(
        default=None,
        max_length=255,
        description="文书标题，缺省用模板名称",
    )


class GeneratedDocOut(BaseModel):
    """模板填充结果（尚未落库，供前端在编辑器里继续修改）。"""

    template_id: int
    template_name: str
    case_id: int | None = None
    case_no: str | None = None
    doc_type: str
    doc_type_label: str
    title: str
    content: str
    filled: dict[str, str] = Field(default_factory=dict, description="已填充变量")
    missing: list[str] = Field(default_factory=list, description="未能取值的变量")


class DocumentItemOut(BaseModel):
    """文书列表项（不含正文，附摘要）。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    case_id: int | None = None
    case_no: str | None = None
    case_title: str | None = None
    client_id: int | None = None
    client_name: str | None = None
    doc_type: str | None = None
    title: str
    status: str
    is_ai_generated: bool = False
    file_url: str | None = None
    created_by: int | None = None
    creator_name: str | None = None
    created_at: datetime
    updated_at: datetime

    # 由 service 层注入的纯文本摘要
    excerpt: str | None = None

    @computed_field  # type: ignore[prop-decorator]
    @property
    def doc_type_label(self) -> str:
        """文书类型中文名：以管理端字典为准，内置常量仅作兜底。"""
        if not self.doc_type:
            return "未分类"
        return dict_cache.label_of(
            "doc_type", self.doc_type, DOC_TYPE_LABELS.get(self.doc_type, self.doc_type)
        )

    @computed_field  # type: ignore[prop-decorator]
    @property
    def status_label(self) -> str:
        """状态中文名。"""
        return DOC_STATUS_LABELS.get(self.status, self.status)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def has_file(self) -> bool:
        """是否已导出过 docx。"""
        return bool(self.file_url)


class DocumentOut(DocumentItemOut):
    """文书详情：附完整正文与 AI 会话信息。"""

    content: str | None = None
    ai_session_id: int | None = None


class DocumentListOut(BaseModel):
    """文书分页列表输出。"""

    total: int
    items: list[DocumentItemOut]


class DocumentExportOut(BaseModel):
    """docx 导出结果。"""

    document_id: int
    file_name: str
    file_url: str
    download_url: str
    file_size: int
    exported_at: datetime

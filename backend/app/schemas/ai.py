"""AI 问答相关的请求/响应模型（任务拆解 9.3.4 ~ 9.3.6）。

与 :mod:`app.schemas.kb` 分开的原因：知识库是**管理端**维护语料的接口，
问答是**每个登录用户**都会用的接口，权限、字段、变更频率都不同，混在一起
会让「谁能改语料」变得不清楚。

SSE 流式接口不出现在这里——它的输出是 ``text/event-stream``，没有 pydantic
响应模型，事件结构在 :mod:`app.services.ai_service` 顶部集中说明。
"""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.document import DOC_TYPES, MAX_CONTENT_LENGTH

__all__ = [
    "AiCaseSummaryIn",
    "AiCaseSummaryOut",
    "AiChatIn",
    "AiContractReviewIn",
    "AiDocArchiveIn",
    "AiDocGenerateIn",
    "AiDocTypeOut",
    "AiMessageOut",
    "AiProfileFields",
    "AiProfileIn",
    "AiProfileInputs",
    "AiProfileOut",
    "AiProfileRisk",
    "AiSessionCreate",
    "AiSessionDetailOut",
    "AiSessionListOut",
    "AiSessionOut",
    "AiSessionUpdate",
    "BusinessChatIn",
]


class AiChatIn(BaseModel):
    """发起一次法律问答（只检索法条与律所知识库）。"""

    question: str = Field(min_length=2, max_length=1000, description="用户问题")
    session_id: int | None = Field(
        default=None, description="续接已有会话；为空则新建"
    )
    top_k: int | None = Field(
        default=None, ge=1, le=10, description="引用条数，缺省 6（设计文档 5~8）"
    )
    source: Literal["law", "firm"] | None = Field(
        default=None, description="检索范围：仅法条 / 仅律所知识 / 全部"
    )

    @field_validator("question")
    @classmethod
    def _strip(cls, v: str) -> str:
        v = v.strip()
        if len(v) < 2:
            raise ValueError("问题太短，请补充具体内容")
        return v


class BusinessChatIn(BaseModel):
    """发起一次「AI督办」问答（只读本人案件与费用台账，不检索法条）。

    没有 ``top_k`` / ``source``：这一侧根本不查向量库。也没有「是否附带业务
    数据」的开关——不带数据这个模块就没有存在意义，开关只会制造"明明问的是
    我的案子却说查不到"的旧问题。
    """

    question: str = Field(min_length=2, max_length=500, description="用户问题")
    session_id: int | None = Field(
        default=None, description="续接已有业务会话；为空则新建"
    )

    @field_validator("question")
    @classmethod
    def _strip(cls, v: str) -> str:
        v = v.strip()
        if len(v) < 2:
            raise ValueError("问题太短，请补充具体内容")
        return v


class AiSessionCreate(BaseModel):
    """新建空会话（前端先开会话、再逐条发问时用）。"""

    title: str | None = Field(default=None, max_length=255, description="会话标题")


class AiSessionUpdate(BaseModel):
    """重命名会话。"""

    title: str = Field(min_length=1, max_length=255)

    @field_validator("title")
    @classmethod
    def _strip(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("标题不能为空")
        return v


class AiSessionOut(BaseModel):
    """会话概要（列表用，不含消息）。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    type: str
    related_id: int | None = None
    title: str | None = None
    created_at: datetime
    updated_at: datetime
    message_count: int = 0


class AiMessageOut(BaseModel):
    """一条消息。``refs`` 是当时的法条快照，用于点击 [n] 展开原文。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    role: str
    content: str
    refs: list[dict[str, Any]] | None = None
    token_usage: int | None = None
    created_at: datetime


class AiSessionDetailOut(AiSessionOut):
    """会话详情：带上全部消息与免责声明（前端固定在底部渲染）。"""

    messages: list[AiMessageOut] = Field(default_factory=list)
    disclaimer: str = ""


class AiSessionListOut(BaseModel):
    """会话分页列表。"""

    total: int
    items: list[AiSessionOut]


# ---------------------------------------------------------------------------
# 9.4 智能文书生成
# ---------------------------------------------------------------------------


class AiDocGenerateIn(BaseModel):
    """发起一次文书初稿生成。

    ``facts`` 缺省取 ``cases.description``；两者都为空时服务层直接报错——
    没有事实的起诉状只会是一堆占位符，不如让律师先把案情补上。
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    doc_type: str = Field(description="文书类型：complaint/response/...")
    case_id: int | None = Field(
        default=None, description="关联案件，用于自动带入当事人、案由、法院等字段"
    )
    facts: str | None = Field(
        default=None,
        max_length=8000,
        description="案件事实，缺省取案件描述；可补充起诉状里需要的情节",
    )
    requirements: str | None = Field(
        default=None,
        max_length=2000,
        description="本次额外要求，如侧重某争议焦点、篇幅、是否列证据清单",
    )
    template_id: int | None = Field(
        default=None, description="引用某个文书模板作为格式骨架"
    )
    title: str | None = Field(
        default=None, max_length=255, description="文书标题，缺省「客户名+类型」"
    )

    @field_validator("doc_type")
    @classmethod
    def _valid_doc_type(cls, v: str) -> str:
        if v not in DOC_TYPES:
            raise ValueError(f"文书类型不合法，可选：{'/'.join(DOC_TYPES)}")
        return v

    @field_validator("facts", "requirements")
    @classmethod
    def _blank_to_none(cls, v: str | None) -> str | None:
        return v or None


class AiDocArchiveIn(BaseModel):
    """把（可能已被律师修改过的）文书正文归档进 ``document`` 表。

    ``content`` 可以是 Markdown（模型原样输出）也可以是 HTML（前端编辑器回传），
    服务层会按内容形态判断，不做二次转义。
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    title: str = Field(min_length=1, max_length=255, description="文书标题")
    doc_type: str = Field(description="文书类型")
    content: str = Field(
        min_length=1, max_length=MAX_CONTENT_LENGTH, description="文书正文"
    )
    case_id: int | None = Field(default=None, description="归档到哪个案件")
    session_id: int | None = Field(
        default=None, description="来源 AI 会话，写入 document.ai_session_id 以便溯源"
    )
    status: str = Field(
        default="draft",
        pattern="^(draft|final|published)$",
        description="draft 草稿 / final 定稿 / published 客户可见",
    )

    @field_validator("doc_type")
    @classmethod
    def _valid_doc_type(cls, v: str) -> str:
        if v not in DOC_TYPES:
            raise ValueError(f"文书类型不合法，可选：{'/'.join(DOC_TYPES)}")
        return v


class AiDocTypeOut(BaseModel):
    """一类文书的元信息，供前端「选类型」步骤展示所需字段与结构。"""

    doc_type: str
    label: str
    required_fields: list[str] = Field(default_factory=list)
    outline: list[str] = Field(default_factory=list)
    rules: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# 9.5 合同风险审查
# ---------------------------------------------------------------------------


class AiContractReviewIn(BaseModel):
    """发起一次合同风险审查。

    文本来源二选一：合同台账里已上传的文件（``docx`` / ``pdf`` / ``txt``），
    或律师直接粘贴的正文。两者都为空时服务层报 400——没有文本可审。
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    text: str | None = Field(
        default=None,
        max_length=100_000,
        description="合同正文，传入则忽略已上传文件（用于扫描件或粘贴稿）",
    )
    focus: str | None = Field(
        default=None,
        max_length=500,
        description="律师特别关注点，如「重点看违约金与管辖」",
    )
    save: bool = Field(
        default=True,
        description="审查完成后是否写回 contract.ai_review_report",
    )

    @field_validator("text", "focus")
    @classmethod
    def _blank_to_none(cls, v: str | None) -> str | None:
        return v or None


# ---------------------------------------------------------------------------
# 9.6 案件摘要
# ---------------------------------------------------------------------------


class AiCaseSummaryIn(BaseModel):
    """发起一次案件摘要。

    摘要输入不是律师手填的，而是从案件档案、时间线、日程、文书、合同与附件
    聚合而来，所以请求体只有两个开关：关注点与是否读取材料。
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    focus: str | None = Field(
        default=None,
        max_length=300,
        description="本次关注点，如「重点梳理劳动争议的仲裁时效与证据缺口」",
    )
    include_materials: bool = Field(
        default=True,
        description="是否读取案件文书/合同/附件；关闭后只依据档案与时间线",
    )

    @field_validator("focus")
    @classmethod
    def _blank_to_none(cls, v: str | None) -> str | None:
        return v or None


class AiCaseSummaryOut(BaseModel):
    """最近一次案件摘要。

    ``content is None`` 表示该律师还没有生成过这个案件的摘要；前端据此显示
    「生成摘要」而不是空报告。摘要按 ``user_id`` 隔离，管理员也看不到他人生成的版本。
    """

    case_id: int
    session_id: int | None = None
    content: str | None = None
    html: str | None = None
    generated_at: datetime | None = None
    disclaimer: str = ""



# ---------------------------------------------------------------------------
# 9.7 客户画像
# ---------------------------------------------------------------------------


class AiProfileIn(BaseModel):
    """生成/刷新客户画像。

    画像输入全部来自客户档案与业务数据，不需要律师填字段；``focus`` 只用于
    临时聚焦（例如「重点看回款风险」），不落库。
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    focus: str | None = Field(
        default=None,
        max_length=300,
        description="本次关注点，如「重点判断是否会流失」",
    )

    @field_validator("focus")
    @classmethod
    def _blank_to_none(cls, v: str | None) -> str | None:
        return v or None


class AiProfileRisk(BaseModel):
    """一条风险点：风险描述 + 数据依据 + 应对动作。"""

    point: str
    basis: str = ""
    action: str = ""


class AiProfileFields(BaseModel):
    """画像主体字段，与 ``client_profile.ai_profile.profile`` 一一对应。"""

    client_type: str
    core_demands: str
    risks: list[AiProfileRisk] = Field(default_factory=list)
    communication: str = ""
    next_actions: str = ""
    tags: list[str] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)
    gaps: list[str] = Field(default_factory=list)


class AiProfileInputs(BaseModel):
    """生成画像时实际读到的数据规模，用于回答「这份画像凭什么」。"""

    counts: dict[str, int] = Field(default_factory=dict)
    stats: dict[str, Any] = Field(default_factory=dict)
    skipped: list[str] = Field(default_factory=list)
    masked: dict[str, Any] = Field(default_factory=dict)


class AiProfileOut(BaseModel):
    """客户画像读取结果。

    ``profile is None`` 表示还没有生成过；前端据此显示「生成画像」。画像按客户
    存档（不是按律师），负责律师之间共享同一份——客户交接时正需要它。
    """

    client_id: int
    profile: AiProfileFields | None = None
    inputs: AiProfileInputs | None = None
    ai_profile_at: datetime | None = None
    generated_by: int | None = None
    model: str | None = None
    elapsed_ms: int | None = None
    disclaimer: str = ""

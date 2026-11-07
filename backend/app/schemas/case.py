"""案件管理相关的请求/响应模型。"""

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator

# 案件状态枚举（与 DB ENUM 一致）
CASE_STATUSES = (
    "consulting",  # 咨询中
    "filed",  # 已立案
    "handling",  # 办理中
    "pending_close",  # 待结案
    "closed",  # 已结案
    "withdrawn",  # 已退案
)

CASE_TYPES = ("litigation", "non_litigation")

EVENT_TYPES = ("filing", "accept", "hearing", "evidence", "judgment", "other")


class CaseCreate(BaseModel):
    """立案入参。"""

    model_config = ConfigDict(str_strip_whitespace=True)

    client_id: int = Field(description="委托客户ID")
    title: str = Field(min_length=1, max_length=255, description="案件标题")
    case_cause: str | None = Field(default=None, max_length=64, description="案由")
    case_type: str = Field(
        default="litigation",
        pattern="^(litigation|non_litigation)$",
        description="诉讼/非诉",
    )
    court: str | None = Field(default=None, max_length=255, description="受理法院/机构")
    opposing_party: str | None = Field(
        default=None, max_length=255, description="对方当事人"
    )
    amount: Decimal = Field(
        default=Decimal(0),
        ge=0,
        le=Decimal("9999999999.99"),
        description="标的额（元，0~9999999999.99）",
    )
    description: str | None = Field(default=None, description="案情描述")

    @field_validator("title")
    @classmethod
    def _check_title(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("案件标题不能为空")
        return v

    @field_validator("amount")
    @classmethod
    def _check_amount(cls, v: Decimal) -> Decimal:
        # 数据库 amount 列为 DECIMAL(12,2)，最多 10 位整数 + 2 位小数
        max_amount = Decimal("9999999999.99")
        if v > max_amount:
            raise ValueError(f"标的额不能超过 {max_amount} 元")
        return v


class CaseUpdate(BaseModel):
    """修改案件入参（全部字段可选）。"""

    model_config = ConfigDict(str_strip_whitespace=True)

    title: str | None = Field(default=None, min_length=1, max_length=255)
    case_cause: str | None = Field(default=None, max_length=64)
    case_type: str | None = Field(default=None, pattern="^(litigation|non_litigation)$")
    court: str | None = Field(default=None, max_length=255)
    opposing_party: str | None = Field(default=None, max_length=255)
    amount: Decimal | None = Field(
        default=None, ge=0, le=Decimal("9999999999.99"), description="标的额"
    )
    description: str | None = Field(default=None)


class CaseStatusIn(BaseModel):
    """状态流转入参。"""

    status: str = Field(description="目标状态")

    @field_validator("status")
    @classmethod
    def _check_status(cls, v: str) -> str:
        if v not in CASE_STATUSES:
            raise ValueError(f"非法状态：{v}")
        return v


class CaseAssignIn(BaseModel):
    """分案入参：指定主办律师与协办律师。"""

    lead_lawyer_id: int = Field(description="主办律师ID")
    assist_lawyer_ids: list[int] = Field(
        default_factory=list, description="协办律师ID列表"
    )

    @field_validator("assist_lawyer_ids")
    @classmethod
    def _check_assist(cls, v: list[int]) -> list[int]:
        # 去重并过滤与主办重复的
        return list(dict.fromkeys(v))


class CaseEventIn(BaseModel):
    """案件事件登记入参。"""

    model_config = ConfigDict(str_strip_whitespace=True)

    event_type: str = Field(
        default="other", pattern="^(filing|accept|hearing|evidence|judgment|other)$"
    )
    event_date: datetime = Field(description="节点时间")
    description: str | None = Field(default=None, max_length=500, description="说明")


class CaseLawyerOut(BaseModel):
    """案件-律师关联输出。"""

    model_config = ConfigDict(from_attributes=True)

    lawyer_id: int
    duty: str
    lawyer_name: str | None = None


class CaseEventOut(BaseModel):
    """案件事件输出。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    case_id: int
    event_type: str
    event_date: datetime
    description: str | None = None
    created_by: int | None = None
    created_at: datetime


class CaseOut(BaseModel):
    """案件基本信息输出。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    case_no: str
    client_id: int
    title: str
    case_cause: str | None = None
    case_type: str
    court: str | None = None
    opposing_party: str | None = None
    amount: Decimal
    status: str
    description: str | None = None
    created_by: int | None = None
    created_at: datetime
    closed_at: datetime | None = None
    # 非数据库字段：主办律师姓名，仅列表查询注入（详情另有 lawyers 列表）
    lead_lawyer_name: str | None = None


class CaseDetailOut(CaseOut):
    """案件详情输出：基本信息 + 承办律师 + 时间线 + 关联档案。"""

    lawyers: list[CaseLawyerOut] = Field(default_factory=list)
    events: list[CaseEventOut] = Field(default_factory=list)
    attachments: list["AttachmentOut"] = Field(default_factory=list)


class CaseListOut(BaseModel):
    """案件分页列表输出。"""

    total: int
    items: list[CaseOut]


class AttachmentOut(BaseModel):
    """附件输出。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    biz_type: str
    biz_id: int
    file_name: str
    file_path: str
    file_size: int
    mime_type: str | None = None
    uploader_id: int | None = None
    created_at: datetime
    # 下载/预览地址，由路由层注入，供前端直接点击
    download_url: str | None = None


CaseDetailOut.model_rebuild()

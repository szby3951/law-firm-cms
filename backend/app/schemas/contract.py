"""合同管理相关的请求/响应模型。"""

from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator

# 合同状态枚举（与 DB ENUM 一致）
CONTRACT_STATUSES = ("draft", "active", "expired", "terminated")

# 合同金额上限：与数据库 DECIMAL(12,2) 对齐（最多 10 位整数 + 2 位小数）
MAX_AMOUNT = Decimal("9999999999.99")


class ContractCreate(BaseModel):
    """新增合同入参。"""

    model_config = ConfigDict(str_strip_whitespace=True)

    client_id: int = Field(description="委托客户ID")
    case_id: int | None = Field(default=None, description="关联案件ID（可选）")
    name: str = Field(min_length=1, max_length=255, description="合同名称")
    contract_type: str | None = Field(default=None, max_length=32, description="合同类型")
    amount: Decimal = Field(
        default=Decimal("0.00"),
        ge=0,
        le=MAX_AMOUNT,
        description="合同金额（元）",
    )
    start_date: date | None = Field(default=None, description="生效日期")
    end_date: date | None = Field(default=None, description="到期日期")
    status: str = Field(
        default="draft",
        pattern="^(draft|active|expired|terminated)$",
        description="合同状态",
    )

    @field_validator("name")
    @classmethod
    def _check_name(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("合同名称不能为空")
        return v

    @field_validator("end_date")
    @classmethod
    def _check_date_range(cls, v: date | None, info) -> date | None:
        """校验到期日期不早于生效日期。"""
        start = info.data.get("start_date")
        if v and start and v < start:
            raise ValueError("到期日期不能早于生效日期")
        return v


class ContractUpdate(BaseModel):
    """修改合同入参（全部字段可选）。"""

    model_config = ConfigDict(str_strip_whitespace=True)

    client_id: int | None = Field(default=None, description="委托客户ID")
    case_id: int | None = Field(default=None, description="关联案件ID")
    name: str | None = Field(default=None, min_length=1, max_length=255)
    contract_type: str | None = Field(default=None, max_length=32)
    amount: Decimal | None = Field(default=None, ge=0, le=MAX_AMOUNT)
    start_date: date | None = Field(default=None)
    end_date: date | None = Field(default=None)
    status: str | None = Field(
        default=None, pattern="^(draft|active|expired|terminated)$"
    )

    @field_validator("name")
    @classmethod
    def _check_name(cls, v: str | None) -> str | None:
        if v is not None and not v.strip():
            raise ValueError("合同名称不能为空")
        return v


class ContractReviewIn(BaseModel):
    """保存 AI 审查报告入参。"""

    report: dict = Field(description="AI 审查报告（结构化 JSON）")


class ContractOut(BaseModel):
    """合同输出。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    case_id: int | None = None
    case_title: str | None = None
    client_id: int
    client_name: str | None = None
    name: str
    contract_type: str | None = None
    amount: Decimal
    start_date: date | None = None
    end_date: date | None = None
    status: str
    file_url: str | None = None
    ai_review_report: dict | None = None
    ai_review_at: datetime | None = None
    created_by: int | None = None
    created_at: datetime
    updated_at: datetime


class ContractListOut(BaseModel):
    """合同分页列表输出。"""

    total: int
    items: list[ContractOut]

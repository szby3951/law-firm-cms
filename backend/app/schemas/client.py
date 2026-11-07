"""客户关系管理相关的请求/响应模型。"""

import re
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.utils import mask_id_no


class ClientCreate(BaseModel):
    """新增客户入参。"""

    model_config = ConfigDict(str_strip_whitespace=True)

    name: str = Field(min_length=1, max_length=64, description="客户姓名/机构名称")
    client_type: str = Field(
        default="personal", pattern="^(personal|company)$", description="个人/机构"
    )
    id_no: str | None = Field(default=None, max_length=64, description="证件号")
    gender: str | None = Field(default=None, max_length=8, description="性别")
    phone: str | None = Field(default=None, max_length=20, description="联系电话")
    address: str | None = Field(default=None, max_length=255, description="联系地址")
    source_channel: str | None = Field(
        default=None, max_length=32, description="来源渠道"
    )
    level: str = Field(
        default="normal", pattern="^(vip|normal)$", description="客户分级"
    )
    status: str = Field(
        default="potential",
        pattern="^(potential|deal|lost)$",
        description="漏斗状态",
    )
    lawyer_id: int | None = Field(
        default=None, description="负责律师ID（管理员可指定）"
    )
    remark: str | None = Field(default=None, description="备注")

    @field_validator("name")
    @classmethod
    def _check_name(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("客户姓名不能为空")
        return v

    @field_validator("phone")
    @classmethod
    def _check_phone(cls, v: str | None) -> str | None:
        if v and not re.fullmatch(r"[\d\-+]{3,20}", v):
            raise ValueError("联系电话格式不正确（仅支持数字、- 和 +，3~20 位）")
        return v


class ClientUpdate(BaseModel):
    """修改客户入参（全部字段可选，仅更新传入项）。"""

    model_config = ConfigDict(str_strip_whitespace=True)

    name: str | None = Field(default=None, min_length=1, max_length=64)
    client_type: str | None = Field(default=None, pattern="^(personal|company)$")
    id_no: str | None = Field(default=None, max_length=64)
    gender: str | None = Field(default=None, max_length=8)
    phone: str | None = Field(default=None, max_length=20)
    address: str | None = Field(default=None, max_length=255)
    source_channel: str | None = Field(default=None, max_length=32)
    level: str | None = Field(default=None, pattern="^(vip|normal)$")
    status: str | None = Field(default=None, pattern="^(potential|deal|lost)$")
    lawyer_id: int | None = Field(default=None, description="负责律师ID")
    remark: str | None = Field(default=None)

    @field_validator("phone")
    @classmethod
    def _check_phone(cls, v: str | None) -> str | None:
        if v is not None and not re.fullmatch(r"[\d\-+]{3,20}", v):
            raise ValueError("联系电话格式不正确（仅支持数字、- 和 +，3~20 位）")
        return v


class ClientOut(BaseModel):
    """客户信息输出（身份证号已脱敏）。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    client_type: str
    id_no: str | None = None
    gender: str | None = None
    phone: str | None = None
    address: str | None = None
    source_channel: str | None = None
    level: str
    status: str
    lawyer_id: int | None = None
    remark: str | None = None
    created_at: datetime

    @field_validator("id_no", mode="before")
    @classmethod
    def _mask(cls, v: str | None) -> str | None:
        """输出时对证件号做脱敏处理。"""
        return mask_id_no(v)


class FollowCreate(BaseModel):
    """新增跟进记录入参。"""

    model_config = ConfigDict(str_strip_whitespace=True)

    content: str = Field(min_length=1, description="跟进内容")
    method: str = Field(
        default="phone",
        pattern="^(phone|wechat|visit|email)$",
        description="跟进方式",
    )
    next_follow_date: date | None = Field(default=None, description="下次跟进日期")

    @field_validator("content")
    @classmethod
    def _check_content(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("跟进内容不能为空")
        return v


class FollowOut(BaseModel):
    """跟进记录输出。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    client_id: int
    user_id: int
    content: str
    method: str
    next_follow_date: date | None = None
    created_at: datetime


class ClientListOut(BaseModel):
    """客户分页列表输出。"""

    total: int
    items: list[ClientOut]

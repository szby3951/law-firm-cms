"""系统设置相关的请求/响应模型：数据字典、律所信息、AI 配置。"""

import re
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator

# 字典分类与取值统一用下划线小写，便于前端拼接与筛选
_CODE_RE = re.compile(r"^[a-z][a-z0-9_]{1,31}$")
_VALUE_RE = re.compile(r"^[A-Za-z0-9_\-]{1,64}$")


class DictItemIn(BaseModel):
    """新增/修改字典项。"""

    model_config = ConfigDict(str_strip_whitespace=True)

    dict_type: str = Field(max_length=32, description="分类，如 case_cause")
    label: str = Field(min_length=1, max_length=64, description="显示文本")
    value: str = Field(max_length=64, description="存储值")
    sort: int = Field(default=0, ge=0, le=9999, description="同分类内排序")

    @field_validator("dict_type")
    @classmethod
    def _check_type(cls, v: str) -> str:
        if not _CODE_RE.fullmatch(v):
            raise ValueError("分类只能用小写字母、数字与下划线，且以字母开头")
        return v

    @field_validator("value")
    @classmethod
    def _check_value(cls, v: str) -> str:
        if not _VALUE_RE.fullmatch(v):
            raise ValueError("存储值只能包含字母、数字、下划线与连字符")
        return v

    @field_validator("label")
    @classmethod
    def _check_label(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("显示文本不能为空")
        return v


class DictItemOut(BaseModel):
    """字典项输出。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    dict_type: str
    label: str
    value: str
    sort: int
    created_at: datetime


class DictTypeOut(BaseModel):
    """字典分类及其条目数，用于前端分类页签。"""

    dict_type: str
    count: int


class DictListOut(BaseModel):
    """字典列表输出（含分类汇总）。"""

    items: list[DictItemOut]
    types: list[DictTypeOut]


class DictOptionOut(BaseModel):
    """下拉候选（业务端只需要标签与取值）。"""

    label: str
    value: str


class DictOptionsOut(BaseModel):
    """全部候选，按分类分组：``{"case_cause": [{label, value}], ...}``。"""

    dicts: dict[str, list[DictOptionOut]]


class FirmInfoIn(BaseModel):
    """律所信息入参。"""

    model_config = ConfigDict(str_strip_whitespace=True)

    name: str = Field(min_length=1, max_length=128, description="律所名称")
    logo: str | None = Field(default=None, max_length=255, description="Logo 地址")
    address: str | None = Field(default=None, max_length=255, description="地址")
    phone: str | None = Field(default=None, max_length=32, description="联系电话")
    intro: str | None = Field(default=None, max_length=2000, description="简介")


class FirmInfoOut(BaseModel):
    """律所信息输出。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    logo: str | None = None
    address: str | None = None
    phone: str | None = None
    intro: str | None = None
    updated_at: datetime


class AIConfigIn(BaseModel):
    """AI 配置入参。

    ``api_key`` 留空表示保持原值（前端不回显明文，避免把脱敏串写回去）。
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    provider: str = Field(min_length=1, max_length=32, description="供应商标识")
    base_url: str = Field(min_length=1, max_length=255, description="OpenAI 兼容接口地址")
    model: str = Field(min_length=1, max_length=64, description="对话模型")
    temperature: Decimal = Field(default=Decimal("0.30"), ge=0, le=2, description="采样温度")
    api_key: str | None = Field(default=None, max_length=255, description="API Key，留空不改")
    embedding_model: str | None = Field(
        default=None, max_length=64, description="嵌入模型（仅记录，运行期不切换）"
    )
    status: int = Field(default=0, ge=0, le=1, description="1=启用，覆盖 .env")

    @field_validator("base_url")
    @classmethod
    def _check_base_url(cls, v: str) -> str:
        if not v.startswith(("http://", "https://")):
            raise ValueError("接口地址需以 http:// 或 https:// 开头")
        return v.rstrip("/")


class AIConfigOut(BaseModel):
    """AI 配置输出：Key 只回脱敏串与「是否已配置」。"""

    provider: str
    base_url: str
    model: str
    temperature: float
    embedding_model: str | None = None
    status: int
    updated_at: datetime
    api_key_masked: str = Field(description="脱敏后的 Key，未配置时为空串")
    api_key_set: bool = Field(description="是否已配置 Key")
    env_model: str = Field(description=".env 中的对话模型，供对照")
    active_model: str = Field(description="当前实际生效的模型")
    active_source: str = Field(description="生效来源：db 或 env")

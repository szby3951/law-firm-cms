"""系统管理相关的请求/响应模型：账号管理、操作日志。"""

import re
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

# 密码长度上限：bcrypt 只取前 72 字节，超长直接拒绝而不是静默截断
MAX_PASSWORD_LENGTH = 72


class AdminUserOut(BaseModel):
    """账号列表中的一行。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    real_name: str
    role: str
    phone: str | None = None
    email: str | None = None
    status: int = Field(description="1=正常 0=禁用")
    created_at: datetime
    case_count: int = Field(default=0, description="承办案件数（仅律师，其余为 0）")
    profile_id: int | None = Field(
        default=None, description="客户档案 ID（仅客户；为空表示尚未建档）"
    )
    profile_name: str | None = Field(default=None, description="客户档案中的姓名")


class AdminUserListOut(BaseModel):
    """账号分页列表输出。"""

    total: int
    items: list[AdminUserOut]


class LawyerCreateIn(BaseModel):
    """开通律师账号入参。"""

    model_config = ConfigDict(str_strip_whitespace=True)

    username: str = Field(
        min_length=3, max_length=64, description="登录账号，一般为工号"
    )
    password: str = Field(
        min_length=6, max_length=MAX_PASSWORD_LENGTH, description="初始密码"
    )
    real_name: str = Field(min_length=1, max_length=64, description="真实姓名")
    phone: str | None = Field(default=None, max_length=20, description="手机号")
    email: str | None = Field(default=None, max_length=128, description="邮箱")

    @field_validator("username")
    @classmethod
    def _check_username(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("账号不能为空")
        return v

    @field_validator("phone")
    @classmethod
    def _check_phone(cls, v: str | None) -> str | None:
        if v and not re.fullmatch(r"1\d{10}", v):
            raise ValueError("手机号格式不正确，应为 11 位数字且以 1 开头")
        return v

    @field_validator("email")
    @classmethod
    def _check_email(cls, v: str | None) -> str | None:
        if v and "@" not in v:
            raise ValueError("邮箱格式不正确")
        return v


class UserStatusIn(BaseModel):
    """启用/禁用账号入参。"""

    status: int = Field(ge=0, le=1, description="1=正常 0=禁用")


class PasswordResetIn(BaseModel):
    """重置密码入参。"""

    new_password: str = Field(
        min_length=6, max_length=MAX_PASSWORD_LENGTH, description="新密码"
    )


class OperationLogOut(BaseModel):
    """操作日志的一行。"""

    id: int
    user_id: int | None = None
    username: str | None = Field(default=None, description="操作人账号")
    real_name: str | None = Field(default=None, description="操作人姓名")
    action: str
    target: str | None = None
    detail: str | None = None
    ip: str | None = None
    created_at: datetime


class OperationLogListOut(BaseModel):
    """操作日志分页列表输出。"""

    total: int
    items: list[OperationLogOut]

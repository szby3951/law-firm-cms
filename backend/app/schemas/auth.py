"""认证与权限相关的请求/响应模型。"""

import re
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

# 密码长度上限：bcrypt 只取前 72 字节，超长直接拒绝而不是静默截断
MAX_PASSWORD_LENGTH = 72


class RegisterIn(BaseModel):
    """客户端注册入参。"""

    model_config = ConfigDict(str_strip_whitespace=True)

    username: str = Field(
        min_length=3, max_length=64, description="登录账号，客户使用手机号"
    )
    password: str = Field(
        min_length=6, max_length=MAX_PASSWORD_LENGTH, description="登录密码"
    )
    real_name: str = Field(default="", max_length=64, description="真实姓名")
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


class LoginIn(BaseModel):
    """登录入参。"""

    model_config = ConfigDict(str_strip_whitespace=True)

    username: str = Field(min_length=1, max_length=64, description="登录账号")
    password: str = Field(
        min_length=1, max_length=MAX_PASSWORD_LENGTH, description="登录密码"
    )


class UserOut(BaseModel):
    """用户信息输出。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    real_name: str
    role: str
    phone: str | None = None
    email: str | None = None
    avatar: str | None = None
    status: int
    created_at: datetime


class TokenOut(BaseModel):
    """登录成功返回：令牌 + 用户信息。"""

    access_token: str
    token_type: str = "bearer"
    expires_in: int = Field(description="有效期（秒）")
    user: UserOut

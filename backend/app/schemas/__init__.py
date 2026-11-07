"""Pydantic 请求/响应模型汇总。"""

from app.schemas.auth import LoginIn, RegisterIn, TokenOut, UserOut
from app.schemas.case import (
    AttachmentOut,
    CaseAssignIn,
    CaseCreate,
    CaseDetailOut,
    CaseEventIn,
    CaseEventOut,
    CaseLawyerOut,
    CaseListOut,
    CaseOut,
    CaseStatusIn,
    CaseUpdate,
)
from app.schemas.client import (
    ClientCreate,
    ClientListOut,
    ClientOut,
    ClientUpdate,
    FollowCreate,
    FollowOut,
)

__all__ = [
    "AttachmentOut",
    "CaseAssignIn",
    "CaseCreate",
    "CaseDetailOut",
    "CaseEventIn",
    "CaseEventOut",
    "CaseLawyerOut",
    "CaseListOut",
    "CaseOut",
    "CaseStatusIn",
    "CaseUpdate",
    "ClientCreate",
    "ClientListOut",
    "ClientOut",
    "ClientUpdate",
    "FollowCreate",
    "FollowOut",
    "LoginIn",
    "RegisterIn",
    "TokenOut",
    "UserOut",
]

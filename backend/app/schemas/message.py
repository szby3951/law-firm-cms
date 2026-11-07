"""沟通留言相关的请求/响应模型。

一条 ``message`` 是会话中的一句话；会话用 ``(client_id, lawyer_id)`` 唯一确定。
``is_read`` 语义是「**对方**是否已读」，具体见 ``app.models.message`` 的说明。
"""

from datetime import datetime

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    computed_field,
    field_validator,
    model_validator,
)

from app.schemas.case import AttachmentOut

# 发送人角色
SENDER_ROLES = ("client", "lawyer")
SENDER_ROLE_LABELS = {
    "client": "客户",
    "lawyer": "律师",
}

# 软删除后的占位文案：撤回与后台删除要能区分，对方才知道发生了什么
DELETE_KIND_TEXT = {
    "recall": "该留言已撤回",
    "admin": "该留言已被管理员删除",
}

# 单条留言正文上限：聊天场景足够，也避免误贴整篇文书
MAX_CONTENT_LENGTH = 2000


class MessageCreate(BaseModel):
    """发送留言入参。

    客户发送时 ``client_id`` 由后端按登录身份推导（传了也会被忽略），
    ``lawyer_id`` 缺省取客户档案上的承办律师；
    律师/管理员发送时 ``client_id`` 必填，``lawyer_id`` 缺省为当前律师。
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    content: str | None = Field(
        default=None,
        max_length=MAX_CONTENT_LENGTH,
        description="正文；可留空，随后通过附件接口补传材料",
    )
    case_id: int | None = Field(default=None, description="关联案件ID")
    client_id: int | None = Field(
        default=None, description="会话客户ID（律师/管理员必填）"
    )
    lawyer_id: int | None = Field(
        default=None, description="会话律师ID（缺省自动推导）"
    )

    @field_validator("content")
    @classmethod
    def _blank_to_none(cls, v: str | None) -> str | None:
        """纯空白视为没填，避免存下一堆空消息。"""
        if v is None:
            return None
        v = v.strip()
        return v or None


class MessageOut(BaseModel):
    """单条留言输出。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    case_id: int | None = None
    client_id: int
    lawyer_id: int | None = None
    sender_id: int
    sender_role: str
    content: str | None = None
    is_read: bool
    created_at: datetime

    # 以下由 service 层聚合注入，便于前端直接渲染
    client_name: str | None = None
    lawyer_name: str | None = None
    sender_name: str | None = None
    case_no: str | None = None
    is_mine: bool = False
    attachments: list[AttachmentOut] = Field(default_factory=list)

    # ---------- 软删除（撤回 / 管理员删除） ----------
    is_deleted: bool = False
    deleted_at: datetime | None = None
    # recall = 发送人自己撤回；admin = 管理员后台删除
    delete_kind: str | None = None
    # 还在撤回窗口内且是本人发的：前端据此显示「撤回」入口
    recallable: bool = False

    @model_validator(mode="after")
    def _mask_deleted(self) -> "MessageOut":
        """已撤回/删除的留言只下发占位信息。

        正文与附件在库里仍然保留（便于审计与误删恢复），但**绝不能再下发给
        会话双方**——否则「撤回」就只是前端把字藏起来，对方刷新接口照样能读到。
        """
        if self.is_deleted:
            self.content = None
            self.attachments = []
            self.recallable = False
        return self

    @computed_field  # type: ignore[prop-decorator]
    @property
    def placeholder(self) -> str | None:
        """软删除后展示的占位文案，未删除时为 None。"""
        if not self.is_deleted:
            return None
        return DELETE_KIND_TEXT.get(self.delete_kind or "recall", DELETE_KIND_TEXT["recall"])

    @computed_field  # type: ignore[prop-decorator]
    @property
    def sender_role_label(self) -> str:
        """角色中文名，前端直接展示。"""
        return SENDER_ROLE_LABELS.get(self.sender_role, self.sender_role)


class MessageListOut(BaseModel):
    """一段会话的消息列表（按时间正序）。

    ``unread`` 是**本会话中发给我且未读**的条数；``client_name`` /
    ``lawyer_name`` 用于聊天窗口标题，空会话也能显示对方是谁。
    """

    total: int
    unread: int = 0
    client_id: int | None = None
    client_name: str | None = None
    lawyer_id: int | None = None
    lawyer_name: str | None = None
    items: list[MessageOut] = Field(default_factory=list)


class ConversationOut(BaseModel):
    """会话摘要：一个客户与一位律师的沟通概况。"""

    client_id: int
    client_name: str | None = None
    lawyer_id: int | None = None
    lawyer_name: str | None = None
    case_no: str | None = None
    last_content: str | None = None
    last_sender_role: str | None = None
    last_at: datetime | None = None
    unread: int = 0
    total: int = 0

    @computed_field  # type: ignore[prop-decorator]
    @property
    def last_sender_role_label(self) -> str | None:
        """最后一条消息的发送人角色中文名。"""
        if not self.last_sender_role:
            return None
        return SENDER_ROLE_LABELS.get(self.last_sender_role, self.last_sender_role)


class ConversationListOut(BaseModel):
    """会话列表输出：含会话总数与未读合计，供红点使用。"""

    total: int
    unread: int = 0
    items: list[ConversationOut] = Field(default_factory=list)


class MessageUnreadOut(BaseModel):
    """未读留言数。"""

    count: int


class MessageReadOut(BaseModel):
    """批量已读结果。"""

    updated: int

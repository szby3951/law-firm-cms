"""站内通知相关的响应模型与枚举常量。

通知由定时任务（``app/scheduler.py``）或业务动作生成，客户端只能看到
「对外」类型（开庭/期限/缴费/合同），律所内部的跟进提醒不下发。
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, computed_field

# 通知类型（与建表注释保持一致）
NOTIFICATION_TYPES = (
    "hearing",
    "deadline",
    "payment",
    "follow",
    "contract",
    "meeting",
    "system",
)

NOTIFICATION_TYPE_LABELS = {
    "hearing": "开庭提醒",
    "deadline": "期限提醒",
    "payment": "缴费提醒",
    "follow": "跟进提醒",
    "contract": "合同预警",
    "meeting": "会议提醒",
    "system": "系统通知",
}

# 客户端可见的通知类型：仅与本人案件相关且对外
CLIENT_VISIBLE_TYPES = ("hearing", "deadline", "payment", "contract")


class NotificationOut(BaseModel):
    """通知输出。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    title: str
    content: str | None = None
    type: str
    is_read: bool
    related_type: str | None = None
    related_id: int | None = None
    created_at: datetime

    @computed_field  # type: ignore[prop-decorator]
    @property
    def type_label(self) -> str:
        """类型中文名，前端直接展示。"""
        return NOTIFICATION_TYPE_LABELS.get(self.type, self.type)


class NotificationListOut(BaseModel):
    """通知列表输出：含总条数与未读数，便于渲染红点。"""

    total: int
    unread: int
    items: list[NotificationOut]


class NotificationUnreadOut(BaseModel):
    """未读数量输出。"""

    count: int


class NotificationReadAllOut(BaseModel):
    """批量已读结果。"""

    updated: int


class ScanResultOut(BaseModel):
    """提醒扫描结果（手动触发或定时任务回执）。"""

    schedule: int = 0
    payment: int = 0
    follow: int = 0
    contract: int = 0
    total: int = 0
    scanned_at: datetime

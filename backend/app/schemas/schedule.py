"""日程相关的请求/响应模型。

覆盖：日程创建/更新、状态标记、列表与日历视图。
"""

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field, computed_field, field_validator

# 日程类型（与 DB ENUM 一致）
SCHEDULE_TYPES = ("hearing", "deadline", "visit", "meeting")
# 日程状态
SCHEDULE_STATUSES = ("pending", "done", "cancelled")

SCHEDULE_TYPE_LABELS = {
    "hearing": "开庭",
    "deadline": "期限",
    "visit": "回访",
    "meeting": "会议",
}

SCHEDULE_STATUS_LABELS = {
    "pending": "待办",
    "done": "已完成",
    "cancelled": "已取消",
}


class ScheduleIn(BaseModel):
    """日程入参（新增，PUT 全量更新复用）。"""

    model_config = ConfigDict(str_strip_whitespace=True)

    title: str = Field(min_length=1, max_length=255, description="日程标题")
    schedule_type: str = Field(
        default="hearing",
        pattern="^(hearing|deadline|visit|meeting)$",
        description="类型：hearing 开庭 / deadline 期限 / visit 回访 / meeting 会议",
    )
    event_date: datetime = Field(description="日程时间")
    remind_at: datetime | None = Field(
        default=None, description="提醒时间，为空则由定时任务按事件前 N 天提醒"
    )
    case_id: int | None = Field(default=None, description="关联案件ID")
    client_id: int | None = Field(default=None, description="关联客户ID")
    user_id: int | None = Field(
        default=None, description="承办律师ID，缺省为当前登录用户（仅管理员可指定他人）"
    )
    status: str = Field(
        default="pending",
        pattern="^(pending|done|cancelled)$",
        description="状态：pending 待办 / done 已完成 / cancelled 已取消",
    )
    remark: str | None = Field(default=None, max_length=500, description="备注")

    @field_validator("title")
    @classmethod
    def _check_title(cls, v: str) -> str:
        """标题去掉首尾空格后不能为空。"""
        text = v.strip()
        if not text:
            raise ValueError("日程标题不能为空")
        return text

    @field_validator("remind_at")
    @classmethod
    def _check_remind_at(cls, v: datetime | None, info) -> datetime | None:
        """提醒时间不得晚于日程时间。"""
        if v is None:
            return v
        event_date = info.data.get("event_date")
        if event_date is not None and v > event_date:
            raise ValueError("提醒时间不能晚于日程时间")
        return v


class ScheduleStatusIn(BaseModel):
    """日程状态标记入参（完成 / 取消 / 恢复待办）。"""

    status: str = Field(
        pattern="^(pending|done|cancelled)$",
        description="目标状态：pending / done / cancelled",
    )


class ScheduleOut(BaseModel):
    """日程输出（含关联案件/客户/律师名称）。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    case_id: int | None = None
    client_id: int | None = None
    user_id: int
    title: str
    schedule_type: str
    event_date: datetime
    remind_at: datetime | None = None
    status: str
    remark: str | None = None
    created_at: datetime

    # 由 service 层注入的关联字段
    case_no: str | None = None
    case_title: str | None = None
    client_name: str | None = None
    lawyer_name: str | None = None

    @computed_field  # type: ignore[prop-decorator]
    @property
    def type_label(self) -> str:
        """类型中文名，前端直接展示。"""
        return SCHEDULE_TYPE_LABELS.get(self.schedule_type, self.schedule_type)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def status_label(self) -> str:
        """状态中文名。"""
        return SCHEDULE_STATUS_LABELS.get(self.status, self.status)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def is_overdue(self) -> bool:
        """待办且已过日程时间 → 视为逾期未办。"""
        return self.status == "pending" and self.event_date < datetime.now()


class ScheduleListOut(BaseModel):
    """日程分页列表输出。"""

    total: int
    items: list[ScheduleOut]


class CalendarDayOut(BaseModel):
    """日历中的一天：当日日程数量与清单。"""

    date: date
    count: int
    items: list[ScheduleOut]


class ScheduleCalendarOut(BaseModel):
    """日历视图输出：按天分组，便于前端直接渲染月/周视图。"""

    start: date
    end: date
    total: int
    days: list[CalendarDayOut]

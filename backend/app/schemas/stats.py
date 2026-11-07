"""统计报表（模块 10）的响应模型。

两类口径：
- ``DashboardOut``：管理员统计大屏，全所数据；
- ``MyStatsOut``：律师个人工作台，仅本人承办案件/负责客户。

营收（``billing``）直接复用 ``BillingStatsOut``，避免与 ``/api/billing/stats``
出现两套口径。
"""

from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, Field

from app.schemas.billing import BillingStatsOut


class KpiOut(BaseModel):
    """管理员大屏顶部指标卡。"""

    active_cases: int = Field(description="在办案件数（咨询中/已立案/办理中/待结案）")
    total_cases: int = Field(description="累计案件数")
    closed_cases: int = Field(description="已结案数（status=closed，退案不计）")
    clients: int = Field(description="在册客户数")
    new_clients: int = Field(description="本月新增客户数")
    month_income: Decimal = Field(description="本月实收金额")
    collection_rate: float = Field(description="回款率（百分比）")
    expiring_contracts: int = Field(description="30 天内到期合同数")
    today_todos: int = Field(description="今日待办日程数（不含已取消）")
    week_todos: int = Field(description="未来 7 天待办日程数")


class MyKpiOut(BaseModel):
    """律师工作台顶部指标卡。"""

    active_cases: int = Field(description="本人在办案件数")
    total_cases: int = Field(description="本人累计承办案件数")
    closed_cases: int = Field(description="本人已结案数")
    clients: int = Field(description="本人负责的客户数")
    month_income: Decimal = Field(description="本人本月创收")
    year_income: Decimal = Field(description="本人本年创收")
    today_todos: int = Field(description="本人今日待办数（不含已取消）")
    week_todos: int = Field(description="本人未来 7 天待办数")
    follow_due: int = Field(description="到期需跟进的客户数")


class TrendPointOut(BaseModel):
    """收案/结案趋势的一个月。"""

    month: str = Field(description="月份，格式 YYYY-MM")
    label: str = Field(description="图表横轴标签，如「11月」或跨年时的「26/1」")
    opened: int = Field(description="当月收案数（按 created_at）")
    closed: int = Field(description="当月结案数（按 closed_at，含退案）")


class DistributionItemOut(BaseModel):
    """通用占比项（案由分布、客户来源等）。"""

    name: str = Field(description="分类名称")
    count: int = Field(description="数量")
    ratio: float = Field(description="占比（百分比，保留两位小数）")


class StatusItemOut(BaseModel):
    """案件状态分布项。"""

    status: str = Field(description="状态标识")
    label: str = Field(description="状态中文名")
    count: int = Field(description="该状态案件数")


class LawyerRankOut(BaseModel):
    """律师办案量与创收排名的一项。

    创收按「主办律师」归属：同一案件若有多名主办，会在各自名下各计一次。
    """

    lawyer_id: int = Field(description="律师ID")
    name: str = Field(description="律师姓名")
    case_count: int = Field(description="承办案件总数（主办+协办）")
    lead_count: int = Field(description="主办案件数")
    assist_count: int = Field(description="协办案件数")
    active_count: int = Field(description="在办案件数")
    closed_count: int = Field(description="已结案数")
    income: Decimal = Field(description="创收金额（主办案件实收合计）")


class ExpiringSummaryOut(BaseModel):
    """合同到期预警分档计数。"""

    within_7: int = Field(description="7 天内到期")
    within_30: int = Field(description="30 天内到期")
    within_60: int = Field(description="60 天内到期")


class TodoSummaryOut(BaseModel):
    """日程待办统计。"""

    today: int = Field(description="今日日程数（不含已取消）")
    week: int = Field(description="未来 7 天待办数")
    overdue: int = Field(description="逾期未办数（待办且时间已过）")


class UpcomingScheduleOut(BaseModel):
    """工作台用到的简要日程。"""

    id: int
    title: str
    schedule_type: str = Field(description="类型：hearing/deadline/visit/meeting")
    type_label: str = Field(description="类型中文名")
    event_date: datetime = Field(description="日程时间")
    case_no: str | None = Field(default=None, description="关联案号")
    client_name: str | None = Field(default=None, description="关联客户")


class FollowUpOut(BaseModel):
    """到期需跟进的客户。"""

    client_id: int
    client_name: str
    next_follow_date: date = Field(description="约定的下次跟进日期")
    overdue_days: int = Field(description="逾期天数，0 表示今天到期")


class DashboardOut(BaseModel):
    """管理员统计大屏。"""

    scope: str = Field(default="all", description="数据范围，固定 all（全所）")
    generated_at: datetime = Field(description="生成时间")
    months: int = Field(description="趋势统计的月份跨度")
    kpi: KpiOut
    case_trend: list[TrendPointOut] = Field(description="收案/结案月度趋势")
    case_status: list[StatusItemOut] = Field(description="案件状态分布")
    case_cause: list[DistributionItemOut] = Field(description="案由分布（前 10）")
    lawyer_ranking: list[LawyerRankOut] = Field(description="律师办案量与创收排名（前 10）")
    client_source: list[DistributionItemOut] = Field(description="客户来源占比")
    billing: BillingStatsOut = Field(description="营收与回款")
    expiring: ExpiringSummaryOut
    todo: TodoSummaryOut


class MyStatsOut(BaseModel):
    """律师个人工作台。"""

    scope: str = Field(default="self", description="数据范围，固定 self（本人）")
    generated_at: datetime = Field(description="生成时间")
    months: int = Field(description="趋势统计的月份跨度")
    kpi: MyKpiOut
    case_trend: list[TrendPointOut] = Field(description="本人收案/结案月度趋势")
    case_status: list[StatusItemOut] = Field(description="本人案件状态分布")
    upcoming_schedules: list[UpcomingScheduleOut] = Field(
        description="未来 7 天日程（最多 5 条）"
    )
    follow_clients: list[FollowUpOut] = Field(
        description="到期需跟进的客户（最多 5 位）"
    )
    billing: BillingStatsOut = Field(description="本人案件营收与回款")

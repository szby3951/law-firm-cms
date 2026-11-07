"""统计报表路由（模块 10.1）。

- ``GET /api/stats/dashboard``：管理员全所大屏；
- ``GET /api/stats/my``：律师个人工作台。

两个接口的数据范围由 ``stat_service`` 按角色判定，客户端无统计权限（403）。
"""

from typing import Annotated

from fastapi import APIRouter, Query

from app.dependencies import CurrentUser, DbSession
from app.schemas.stats import DashboardOut, MyStatsOut
from app.services import stat_service

router = APIRouter()


@router.get(
    "/dashboard",
    response_model=DashboardOut,
    summary="统计大屏（管理员 · 全所）",
)
async def stats_dashboard(
    db: DbSession,
    user: CurrentUser,
    months: Annotated[
        int, Query(ge=1, le=36, description="收案趋势的月份跨度")
    ] = 12,
) -> DashboardOut:
    """管理员统计大屏。

    返回 KPI 指标、收案/结案月度趋势、案件状态分布、案由分布、律师办案量与
    创收排名、客户来源占比、营收与回款、合同到期预警、日程待办计数。
    """
    return await stat_service.dashboard(db, user, months=months)


@router.get(
    "/my",
    response_model=MyStatsOut,
    summary="个人工作台（律师 · 本人）",
)
async def stats_my(
    db: DbSession,
    user: CurrentUser,
    months: Annotated[
        int, Query(ge=1, le=36, description="收案趋势的月份跨度")
    ] = 6,
) -> MyStatsOut:
    """律师个人工作台。

    数据范围仅限本人承办的案件与本人负责的客户：KPI、收案/结案趋势、
    案件状态分布、未来 7 天日程、到期需跟进客户、本人营收与回款。
    """
    return await stat_service.my_stats(db, user, months=months)

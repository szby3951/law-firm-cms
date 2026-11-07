"""模块 10.1 统计接口核查：指标正确性、角色数据范围、越权拦截。

用法::

    cd backend
    .venv/Scripts/python.exe scripts/stats_check.py --base http://127.0.0.1:8000

做法：
- 用 ``create_access_token`` 直接签发三种角色令牌（不改任何账号密码）；
- 走真实 HTTP 调用 ``/api/stats/dashboard``、``/api/stats/my``；
- 关键数字用独立原生 SQL 交叉核对，任一项不符即 FAIL 并非零退出。
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

import httpx
from sqlalchemy import select, text

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.security import create_access_token
from app.database import SessionLocal
from app.models.user import User

FAILED: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"  [{'OK  ' if ok else 'FAIL'}] {name}{(' — ' + detail) if detail else ''}")
    if not ok:
        FAILED.append(name)


def dec(value) -> Decimal:
    if value is None:
        return Decimal(0)
    return Decimal(str(value))


async def pick_user(db, role: str) -> User:
    """取该角色下 id 最小的正常账号。"""
    rows = (
        (
            await db.execute(
                select(User)
                .where(User.role == role, User.status == 1)
                .order_by(User.id.asc())
            )
        )
        .scalars()
        .all()
    )
    if not rows:
        raise SystemExit(f"库中没有可用的 {role} 账号")
    return rows[0]


async def scalar(db, sql: str, params: dict | None = None) -> Decimal:
    """执行原生 SQL 取单个数值（用于与接口结果交叉核对）。"""
    value = await db.scalar(text(sql), params or {})
    return dec(value)


async def get(client: httpx.AsyncClient, path: str, token: str | None) -> httpx.Response:
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    return await client.get(path, headers=headers)


def show_dashboard(data: dict) -> None:
    kpi = data["kpi"]
    print(
        "  KPI: 在办 {active} / 累计 {total} / 结案 {closed} / 客户 {clients}"
        "（本月新增 {new}）/ 本月实收 {income} / 回款率 {rate}%"
        " / 30天到期 {exp} / 今日待办 {today} / 7天待办 {week}".format(
            active=kpi["active_cases"],
            total=kpi["total_cases"],
            closed=kpi["closed_cases"],
            clients=kpi["clients"],
            new=kpi["new_clients"],
            income=kpi["month_income"],
            rate=kpi["collection_rate"],
            exp=kpi["expiring_contracts"],
            today=kpi["today_todos"],
            week=kpi["week_todos"],
        )
    )
    trend = data["case_trend"]
    print(f"  趋势({data['months']} 个月): {len(trend)} 个点")
    print("    " + "  ".join(f"{p['label']}:{p['opened']}/{p['closed']}" for p in trend))
    status = "  ".join(f"{s['label']}{s['count']}" for s in data["case_status"])
    print(f"  状态分布: {status}")
    print("  案由: " + "  ".join(f"{c['name']}{c['count']}({c['ratio']}%)" for c in data["case_cause"]))
    print("  来源: " + "  ".join(f"{c['name']}{c['count']}({c['ratio']}%)" for c in data["client_source"]))
    print("  律师排名:")
    for row in data["lawyer_ranking"]:
        print(
            f"    {row['name']}: 承办{row['case_count']}"
            f"（主办{row['lead_count']}/协办{row['assist_count']}）"
            f" 在办{row['active_count']} 结案{row['closed_count']}"
            f" 创收 {row['income']}"
        )
    b = data["billing"]
    print(
        f"  营收: 本月 {b['month_income']} / 应收 {b['total_due']} / 已收 {b['total_paid']}"
        f" / 未收 {b['total_unpaid']} / 回款率 {b['collection_rate']}%"
        f" / 逾期 {b['overdue_amount']}（{b['overdue_count']} 期）"
    )
    e = data["expiring"]
    print(f"  合同到期: 7天 {e['within_7']} / 30天 {e['within_30']} / 60天 {e['within_60']}")
    t = data["todo"]
    print(f"  待办: 今日 {t['today']} / 未来7天 {t['week']} / 逾期 {t['overdue']}")


def show_my(data: dict) -> None:
    kpi = data["kpi"]
    print(
        "  KPI: 在办 {active} / 累计 {total} / 结案 {closed} / 客户 {clients}"
        " / 本月创收 {m} / 本年创收 {y} / 今日待办 {today} / 7天待办 {week}"
        " / 待跟进 {follow}".format(
            active=kpi["active_cases"],
            total=kpi["total_cases"],
            closed=kpi["closed_cases"],
            clients=kpi["clients"],
            m=kpi["month_income"],
            y=kpi["year_income"],
            today=kpi["today_todos"],
            week=kpi["week_todos"],
            follow=kpi["follow_due"],
        )
    )
    print(f"  趋势({data['months']} 个月): " + "  ".join(
        f"{p['label']}:{p['opened']}/{p['closed']}" for p in data["case_trend"]
    ))
    print("  状态: " + "  ".join(f"{s['label']}{s['count']}" for s in data["case_status"]))
    print(f"  未来日程: {len(data['upcoming_schedules'])} 条")
    for item in data["upcoming_schedules"]:
        print(f"    {item['event_date'][:16]} {item['type_label']} {item['title']}")
    print(f"  待跟进客户: {len(data['follow_clients'])} 位")
    for item in data["follow_clients"]:
        print(f"    {item['client_name']} 约定 {item['next_follow_date']} 逾期 {item['overdue_days']} 天")
    b = data["billing"]
    print(f"  营收: 本月 {b['month_income']} / 应收 {b['total_due']} / 已收 {b['total_paid']} / 回款率 {b['collection_rate']}%")


async def main(base: str) -> int:
    async with SessionLocal() as db:
        admin = await pick_user(db, "admin")
        lawyer = await pick_user(db, "lawyer")
        client_user = await pick_user(db, "client")

        sql_cases = await scalar(db, "select count(*) from cases")
        sql_closed = await scalar(db, "select count(*) from cases where status = 'closed'")
        sql_clients = await scalar(db, "select count(*) from client_profile")
        sql_paid = await scalar(db, "select coalesce(sum(amount), 0) from payment")
        sql_my_cases = await scalar(
            db,
            "select count(distinct case_id) from case_lawyer where lawyer_id = :p0",
            {"p0": lawyer.id},
        )
        sql_my_clients = await scalar(
            db,
            "select count(*) from client_profile where lawyer_id = :p0",
            {"p0": lawyer.id},
        )
        sql_expiring_30 = await scalar(
            db,
            "select count(*) from contract where status = 'active'"
            " and end_date is not null and end_date >= curdate()"
            " and end_date <= date_add(curdate(), interval 30 day)",
        )

    tokens = {
        "admin": create_access_token(admin.id, admin.role),
        "lawyer": create_access_token(lawyer.id, lawyer.role),
        "client": create_access_token(client_user.id, client_user.role),
    }
    print(f"账号: admin={admin.id}({admin.real_name}) lawyer={lawyer.id}({lawyer.real_name}) "
          f"client={client_user.id}")

    async with httpx.AsyncClient(base_url=base, timeout=30) as http:
        print("\n== 管理员大屏 /api/stats/dashboard ==")
        resp = await get(http, "/api/stats/dashboard?months=12", tokens["admin"])
        check("管理员调用大屏返回 200", resp.status_code == 200, f"HTTP {resp.status_code}")
        if resp.status_code == 200:
            data = resp.json()
            show_dashboard(data)
            kpi = data["kpi"]
            check("累计案件与 SQL 一致", kpi["total_cases"] == int(sql_cases),
                  f'{kpi["total_cases"]} vs {int(sql_cases)}')
            check("结案数与 SQL 一致", kpi["closed_cases"] == int(sql_closed),
                  f'{kpi["closed_cases"]} vs {int(sql_closed)}')
            check("客户数与 SQL 一致", kpi["clients"] == int(sql_clients),
                  f'{kpi["clients"]} vs {int(sql_clients)}')
            check("已收合计与 SQL 一致", dec(data["billing"]["total_paid"]) == sql_paid,
                  f'{data["billing"]["total_paid"]} vs {sql_paid}')
            check(
                "状态分布合计 = 累计案件",
                sum(s["count"] for s in data["case_status"]) == kpi["total_cases"],
            )
            check("趋势点数 = months", len(data["case_trend"]) == data["months"])
            check(
                "趋势收案合计 ≤ 累计案件（仅时间窗内）",
                sum(p["opened"] for p in data["case_trend"]) <= kpi["total_cases"],
            )
            check(
                "案由占比合计 ≤ 100（前 10 截断，含四舍五入误差）",
                sum(c["ratio"] for c in data["case_cause"]) <= 100.05,
            )
            check(
                "来源占比合计 = 100",
                abs(sum(c["ratio"] for c in data["client_source"]) - 100) < 0.05
                or not data["client_source"],
            )
            check(
                "律师排名按创收降序",
                [dec(r["income"]) for r in data["lawyer_ranking"]]
                == sorted((dec(r["income"]) for r in data["lawyer_ranking"]), reverse=True),
            )
            check(
                "主办+协办 = 承办数",
                all(r["lead_count"] + r["assist_count"] == r["case_count"]
                    for r in data["lawyer_ranking"]),
            )
            exp = data["expiring"]
            check(
                "到期分档单调不减",
                exp["within_7"] <= exp["within_30"] <= exp["within_60"],
                f'7={exp["within_7"]} 30={exp["within_30"]} 60={exp["within_60"]}',
            )
            check(
                "30 天到期数与 SQL 一致",
                exp["within_30"] == int(sql_expiring_30),
                f'{exp["within_30"]} vs {int(sql_expiring_30)}',
            )
            check(
                "KPI 到期数 = 30 天档",
                kpi["expiring_contracts"] == exp["within_30"],
            )

        print("\n== 律师个人台 /api/stats/my ==")
        resp = await get(http, "/api/stats/my?months=6", tokens["lawyer"])
        check("律师调用个人台返回 200", resp.status_code == 200, f"HTTP {resp.status_code}")
        if resp.status_code == 200:
            data = resp.json()
            show_my(data)
            kpi = data["kpi"]
            check("本人承办案件数与 SQL 一致", kpi["total_cases"] == int(sql_my_cases),
                  f'{kpi["total_cases"]} vs {int(sql_my_cases)}')
            check("本人客户数与 SQL 一致", kpi["clients"] == int(sql_my_clients),
                  f'{kpi["clients"]} vs {int(sql_my_clients)}')
            check(
                "状态分布合计 = 本人案件数",
                sum(s["count"] for s in data["case_status"]) == kpi["total_cases"],
            )
            check("趋势点数 = months", len(data["case_trend"]) == data["months"])
            check("scope = self", data["scope"] == "self")
            check(
                "待跟进总数 ≥ 展示条数（列表最多 5）",
                kpi["follow_due"] >= len(data["follow_clients"]),
            )
            today = date.today()
            check(
                "待跟进逾期天数与约定日期一致",
                all(
                    item["overdue_days"]
                    == max(0, (today - date.fromisoformat(item["next_follow_date"])).days)
                    for item in data["follow_clients"]
                ),
            )

        print("\n== 越权与边界 ==")
        resp = await get(http, "/api/stats/dashboard", tokens["lawyer"])
        check("律师访问大屏被拒 403", resp.status_code == 403, f"HTTP {resp.status_code}")
        resp = await get(http, "/api/stats/my", tokens["admin"])
        check("管理员访问个人台被拒 403", resp.status_code == 403, f"HTTP {resp.status_code}")
        resp = await get(http, "/api/stats/my", tokens["client"])
        check("客户访问个人台被拒 403", resp.status_code == 403, f"HTTP {resp.status_code}")
        resp = await get(http, "/api/stats/dashboard", None)
        check("未登录取大屏 401", resp.status_code == 401, f"HTTP {resp.status_code}")
        resp = await get(http, "/api/stats/dashboard?months=99", tokens["admin"])
        check("months 越界 422", resp.status_code == 422, f"HTTP {resp.status_code}")
        resp = await get(http, "/api/stats/my?months=0", tokens["lawyer"])
        check("months=0 被拒 422", resp.status_code == 422, f"HTTP {resp.status_code}")

    print()
    if FAILED:
        print(f"FAILED {len(FAILED)} 项: {', '.join(FAILED)}")
        return 1
    print("全部检查通过")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="模块10.1 统计接口核查")
    parser.add_argument("--base", default="http://127.0.0.1:8000", help="后端地址")
    args = parser.parse_args()
    sys.exit(asyncio.run(main(args.base)))

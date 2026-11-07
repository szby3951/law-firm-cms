"""模块 11 账号管理 / 操作日志核查：分页、筛选、权限、保护规则、审计落库。

用法::

    cd backend
    .venv/Scripts/python.exe scripts/admin_check.py --base http://127.0.0.1:8000

做法：
- 用 ``create_access_token`` 签发三种角色令牌，不改动任何既有账号密码；
- 走真实 HTTP 调用 ``/api/admin/users`` 等接口；
- 创建的临时律师账号在结束时**自动删除**（含其审计日志），库恢复原状；
- 任一项断言失败即打印 FAIL 并以非零码退出。
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

import httpx
from sqlalchemy import delete, func, select

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.security import create_access_token
from app.database import SessionLocal
from app.models.log import OperationLog
from app.models.user import User

BASE = "http://127.0.0.1:8000"
FAILED: list[str] = []
TEMP_USERNAME = "__tmp_admin_check__"


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"  [{'OK  ' if ok else 'FAIL'}] {name}{(' — ' + detail) if detail else ''}")
    if not ok:
        FAILED.append(name)


async def pick_user(db, role: str) -> User:
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


def headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def cleanup(db) -> None:
    """删除临时账号与其审计日志。"""
    user = await db.scalar(select(User).where(User.username == TEMP_USERNAME))
    if user is not None:
        await db.execute(
            delete(OperationLog).where(OperationLog.target == f"user:{user.id}")
        )
        await db.delete(user)
        await db.commit()


async def main() -> None:
    parser = argparse.ArgumentParser(description="模块 11 账号管理核查")
    parser.add_argument("--base", default=BASE, help="后端地址")
    args = parser.parse_args()
    base = args.base.rstrip("/")

    async with SessionLocal() as db:
        admin = await pick_user(db, "admin")
        lawyer = await pick_user(db, "lawyer")
        client_user = await pick_user(db, "client")
        admin_tok = create_access_token(admin.id, admin.role)
        lawyer_tok = create_access_token(lawyer.id, lawyer.role)
        client_tok = create_access_token(client_user.id, client_user.role)

        await cleanup(db)  # 上一次异常退出的残留

        async with httpx.AsyncClient(base_url=base, timeout=20) as http:
            # ---------- 账号列表 ----------
            print("\n== 账号列表 ==")
            r = await http.get(
                "/api/admin/users", params={"role": "lawyer"}, headers=headers(admin_tok)
            )
            check("管理员可查询律师账号列表", r.status_code == 200, f"HTTP {r.status_code}")
            data = r.json() if r.status_code == 200 else {}
            total_sql = int(
                await db.scalar(
                    select(func.count())
                    .select_from(User)
                    .where(User.role == "lawyer")
                )
                or 0
            )
            check(
                "总数与 SQL 一致",
                data.get("total") == total_sql,
                f"{data.get('total')} vs {total_sql}",
            )
            check(
                "列表项角色均为 lawyer",
                all(i["role"] == "lawyer" for i in data.get("items", [])),
            )
            check(
                "律师带承办案件数",
                all("case_count" in i for i in data.get("items", [])),
            )

            r = await http.get(
                "/api/admin/users",
                params={"keyword": lawyer.username},
                headers=headers(admin_tok),
            )
            check(
                "账号关键词搜索命中",
                r.status_code == 200 and r.json().get("total", 0) >= 1,
                f"total={r.json().get('total') if r.status_code == 200 else '-'}",
            )

            r = await http.get(
                "/api/admin/users",
                params={"status": 5},
                headers=headers(admin_tok),
            )
            check("status 越界被拒 422", r.status_code == 422, f"HTTP {r.status_code}")

            r = await http.get(
                "/api/admin/users",
                params={"role": "hacker"},
                headers=headers(admin_tok),
            )
            check("非法角色参数被拒 400", r.status_code == 400, f"HTTP {r.status_code}")

            # ---------- 开通律师 ----------
            print("\n== 开通律师账号 ==")
            payload = {
                "username": TEMP_USERNAME,
                "password": "tmp123456",
                "real_name": "核查临时律师",
                "phone": "13800000001",
                "email": "tmp@example.com",
            }
            r = await http.post(
                "/api/admin/users/lawyers", json=payload, headers=headers(admin_tok)
            )
            check("开通成功返回 201", r.status_code == 201, f"HTTP {r.status_code}")
            created = r.json() if r.status_code == 201 else {}
            new_id = created.get("id")
            check("新账号角色为 lawyer", created.get("role") == "lawyer")
            check("新账号默认启用", created.get("status") == 1)

            r = await http.post(
                "/api/admin/users/lawyers", json=payload, headers=headers(admin_tok)
            )
            check("账号重复被拒 409", r.status_code == 409, f"HTTP {r.status_code}")

            r = await http.post(
                "/api/admin/users/lawyers",
                json={**payload, "username": "ab"},
                headers=headers(admin_tok),
            )
            check("账号过短被拒 422", r.status_code == 422, f"HTTP {r.status_code}")

            r = await http.post(
                "/api/admin/users/lawyers",
                json={**payload, "username": "tmp_phone", "phone": "123"},
                headers=headers(admin_tok),
            )
            check("手机号格式错误被拒 422", r.status_code == 422, f"HTTP {r.status_code}")

            # ---------- 禁用 / 启用 ----------
            print("\n== 禁用与恢复 ==")
            if new_id:
                r = await http.patch(
                    f"/api/admin/users/{new_id}/status",
                    json={"status": 0},
                    headers=headers(admin_tok),
                )
                check("禁用成功", r.status_code == 200 and r.json()["status"] == 0)

                tmp_tok = create_access_token(new_id, "lawyer")
                r = await http.get("/api/auth/me", headers=headers(tmp_tok))
                check("被禁用账号无法访问 403", r.status_code == 403, f"HTTP {r.status_code}")

                r = await http.patch(
                    f"/api/admin/users/{new_id}/status",
                    json={"status": 1},
                    headers=headers(admin_tok),
                )
                check("启用成功", r.status_code == 200 and r.json()["status"] == 1)

                r = await http.get("/api/auth/me", headers=headers(tmp_tok))
                check("启用后可正常访问", r.status_code == 200, f"HTTP {r.status_code}")

                r = await http.patch(
                    f"/api/admin/users/{new_id}/status",
                    json={"status": 7},
                    headers=headers(admin_tok),
                )
                check("状态值越界被拒 422", r.status_code == 422, f"HTTP {r.status_code}")

                # 保护规则
                r = await http.patch(
                    f"/api/admin/users/{admin.id}/status",
                    json={"status": 0},
                    headers=headers(admin_tok),
                )
                check("不能禁用自己 400", r.status_code == 400, f"HTTP {r.status_code}")

                other_admin = await db.scalar(
                    select(User).where(User.role == "admin", User.id != admin.id)
                )
                if other_admin is not None:
                    r = await http.post(
                        f"/api/admin/users/{other_admin.id}/reset-password",
                        json={"new_password": "hack123456"},
                        headers=headers(admin_tok),
                    )
                    check(
                        "不能重置其他管理员密码 400",
                        r.status_code == 400,
                        f"HTTP {r.status_code}",
                    )
                else:
                    check("库中只有一个管理员，跳过跨管理员用例", True, "仅 1 个管理员")

                # ---------- 重置密码 ----------
                print("\n== 重置密码 ==")
                r = await http.post(
                    f"/api/admin/users/{new_id}/reset-password",
                    json={"new_password": "new123456"},
                    headers=headers(admin_tok),
                )
                check("重置密码成功", r.status_code == 200, f"HTTP {r.status_code}")

                r = await http.post(
                    "/api/auth/login",
                    json={"username": TEMP_USERNAME, "password": "new123456"},
                )
                check("新密码可登录", r.status_code == 200, f"HTTP {r.status_code}")

                r = await http.post(
                    "/api/auth/login",
                    json={"username": TEMP_USERNAME, "password": "tmp123456"},
                )
                check("旧密码失效 401", r.status_code == 401, f"HTTP {r.status_code}")

                r = await http.post(
                    f"/api/admin/users/{new_id}/reset-password",
                    json={"new_password": "123"},
                    headers=headers(admin_tok),
                )
                check("新密码过短被拒 422", r.status_code == 422, f"HTTP {r.status_code}")

                r = await http.post(
                    "/api/admin/users/99999999/reset-password",
                    json={"new_password": "new123456"},
                    headers=headers(admin_tok),
                )
                check("不存在的账号 404", r.status_code == 404, f"HTTP {r.status_code}")

            # ---------- 操作日志 ----------
            print("\n== 操作日志 ==")
            r = await http.get("/api/admin/logs", headers=headers(admin_tok))
            check("管理员可查日志", r.status_code == 200, f"HTTP {r.status_code}")
            logs = r.json() if r.status_code == 200 else {}
            # MySQL 默认可重复读：会话内事务未结束会读到旧快照，
            # 计数前先回滚一次，否则会漏掉刚才接口写入的审计日志
            await db.rollback()
            log_total = int(
                await db.scalar(select(func.count()).select_from(OperationLog)) or 0
            )
            check(
                "日志总数与 SQL 一致",
                logs.get("total") == log_total,
                f"{logs.get('total')} vs {log_total}",
            )
            check(
                "日志按时间倒序",
                all(
                    logs["items"][i]["created_at"] >= logs["items"][i + 1]["created_at"]
                    for i in range(len(logs.get("items", [])) - 1)
                ),
            )

            r = await http.get(
                "/api/admin/logs",
                params={"keyword": TEMP_USERNAME},
                headers=headers(admin_tok),
            )
            hits = r.json().get("items", []) if r.status_code == 200 else []
            check(
                "本次操作的审计日志已落库",
                len(hits) >= 3,
                f"命中 {len(hits)} 条（开通/禁用/启用/重置）",
            )
            check(
                "日志带操作人账号",
                all(i.get("username") for i in hits) if hits else False,
            )

            r = await http.get(
                "/api/admin/logs",
                params={"action": "login", "page_size": 5},
                headers=headers(admin_tok),
            )
            items = r.json().get("items", []) if r.status_code == 200 else []
            check("动作筛选生效", all(i["action"] == "login" for i in items))

            r = await http.get(
                "/api/admin/logs",
                params={"start": "2000-01-01", "end": "2000-01-02"},
                headers=headers(admin_tok),
            )
            check(
                "时间范围筛选生效（早期无数据）",
                r.status_code == 200 and r.json().get("total") == 0,
                f"total={r.json().get('total') if r.status_code == 200 else '-'}",
            )

            r = await http.get(
                "/api/admin/logs",
                params={"start": "2030-01-01", "end": "2020-01-01"},
                headers=headers(admin_tok),
            )
            check(
                "起止日期颠倒返回空而非报错",
                r.status_code == 200 and r.json().get("total") == 0,
                f"HTTP {r.status_code}",
            )

            # ---------- 越权 ----------
            print("\n== 越权拦截 ==")
            r = await http.get("/api/admin/users", headers=headers(lawyer_tok))
            check("律师查账号列表 403", r.status_code == 403, f"HTTP {r.status_code}")
            r = await http.get("/api/admin/logs", headers=headers(lawyer_tok))
            check("律师查操作日志 403", r.status_code == 403, f"HTTP {r.status_code}")
            r = await http.post(
                "/api/admin/users/lawyers",
                json=payload,
                headers=headers(lawyer_tok),
            )
            check("律师开通账号 403", r.status_code == 403, f"HTTP {r.status_code}")
            r = await http.get("/api/admin/users", headers=headers(client_tok))
            check("客户查账号列表 403", r.status_code == 403, f"HTTP {r.status_code}")
            r = await http.get("/api/admin/users")
            check("未登录取列表 401", r.status_code == 401, f"HTTP {r.status_code}")

        # ---------- 收尾 ----------
        await cleanup(db)
        left = await db.scalar(
            select(User).where(User.username == TEMP_USERNAME)
        )
        check("临时账号已清理", left is None)

    print()
    if FAILED:
        print(f"失败 {len(FAILED)} 项：" + "，".join(FAILED))
        sys.exit(1)
    print("全部检查通过")


if __name__ == "__main__":
    asyncio.run(main())

"""账号开通口径核查：客户自助注册免审核、律师只能由管理员在后台开通。

用法::

    cd backend
    .venv/Scripts/python.exe scripts/account_flow_check.py --base http://127.0.0.1:8000

覆盖：
1. 客户注册即启用（无审核态），可立刻登录；
2. 注册即建档：新客户自动生成档案并绑定账号；
3. 注册时若律师已代录同手机号档案，则认领该档案而非重复建档；
4. 注册接口忽略 role 字段，自助注册无法拿到 lawyer/admin 身份；
5. 客户 token 访问管理员接口 403；
6. 管理员开通律师账号后可登录，且只能访问律师范围接口；
7. 律师工号重复开通返回 409；
8. 临时账号、临时档案及其审计日志在结束时清理。
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

import httpx
from sqlalchemy import delete, or_, select

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.database import SessionLocal
from app.models.client import ClientProfile
from app.models.log import OperationLog
from app.models.user import User

BASE = "http://127.0.0.1:8000"
FAILED: list[str] = []
SUFFIX = "8699"
TEMP_CLIENT = f"139{SUFFIX}0001"
TEMP_CLIENT2 = f"139{SUFFIX}0002"
TEMP_LAWYER = "__tmp_flow_lawyer__"
TEMP_PASSWORD = "flow123456"


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"  [{'OK  ' if ok else 'FAIL'}] {name}{(' — ' + detail) if detail else ''}")
    if not ok:
        FAILED.append(name)


def headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def cleanup() -> None:
    """删除临时账号、临时客户档案与它们的审计日志。"""
    async with SessionLocal() as db:
        # 档案先删：注册即建档会留下 client_profile 记录
        await db.execute(
            delete(ClientProfile).where(
                ClientProfile.phone.in_([TEMP_CLIENT, TEMP_CLIENT2])
            )
        )
        rows = (
            (
                await db.execute(
                    select(User).where(
                        or_(
                            User.username == TEMP_CLIENT,
                            User.username == TEMP_CLIENT2,
                            User.username == TEMP_LAWYER,
                        )
                    )
                )
            )
            .scalars()
            .all()
        )
        for user in rows:
            await db.execute(delete(OperationLog).where(OperationLog.user_id == user.id))
            await db.execute(
                delete(OperationLog).where(OperationLog.target == f"user:{user.id}")
            )
            await db.delete(user)
        await db.commit()
        if rows:
            print(f"\n已清理临时账号 {len(rows)} 个及其审计日志")


async def seed_unlinked_profile() -> None:
    """预置一条未绑定账号的档案，用于验证注册时的「认领」逻辑。"""
    async with SessionLocal() as db:
        db.add(
            ClientProfile(
                user_id=None,
                name="流程核查客户-律师代录",
                client_type="personal",
                phone=TEMP_CLIENT2,
                source_channel="转介绍",
                level="normal",
                status="potential",
                remark="核查脚本预置：应被注册账号认领，而不是重复建档",
            )
        )
        await db.commit()


async def admin_token(base: str) -> tuple[str, dict]:
    """用库中第一个启用的管理员签发令牌（不改动其密码）。"""
    from app.core.security import create_access_token

    async with SessionLocal() as db:
        admin = await db.scalar(
            select(User).where(User.role == "admin", User.status == 1).order_by(User.id.asc())
        )
        if admin is None:
            raise SystemExit("库中没有启用的管理员账号")
    return create_access_token(admin.id, admin.role), {
        "id": admin.id,
        "username": admin.username,
    }


async def main() -> None:
    parser = argparse.ArgumentParser(description="账号开通口径核查")
    parser.add_argument("--base", default=BASE)
    args = parser.parse_args()
    base = args.base.rstrip("/")

    token, admin = await admin_token(base)
    print(f"管理员: #{admin['id']} {admin['username']}\n")

    await cleanup()
    await seed_unlinked_profile()  # 为「认领」分支预置一条代录档案

    async with httpx.AsyncClient(base_url=base, timeout=20.0) as client:
        # ---------- 一、客户注册：免审核 ----------
        print("一、客户自助注册")
        payload = {
            "username": TEMP_CLIENT,
            "password": TEMP_PASSWORD,
            "real_name": "流程核查客户",
            "phone": TEMP_CLIENT,
            "role": "lawyer",  # 试图提权，应被忽略
            "status": 0,
        }
        r = await client.post("/api/auth/register", json=payload)
        data = r.json() if r.status_code < 300 else {}
        check("注册成功", r.status_code in (200, 201), f"HTTP {r.status_code}")
        check("角色固定为 client（忽略请求中的 role）", data.get("role") == "client", str(data.get("role")))
        check("注册即启用，无待审核态", data.get("status") == 1, f"status={data.get('status')}")

        # 注册即建档：账号与档案同事务落库
        async with SessionLocal() as db:
            await db.rollback()
            new_user = await db.scalar(select(User).where(User.username == TEMP_CLIENT))
            profiles = (
                (
                    await db.execute(
                        select(ClientProfile).where(ClientProfile.phone == TEMP_CLIENT)
                    )
                )
                .scalars()
                .all()
            )
            check("注册即建档：自动生成客户档案", len(profiles) == 1, f"{len(profiles)} 条")
            check(
                "档案绑定到新账号",
                len(profiles) == 1
                and new_user is not None
                and profiles[0].user_id == new_user.id,
            )
            check(
                "档案来源与备注标记为自助注册",
                len(profiles) == 1
                and profiles[0].source_channel == "网络"
                and "自助注册" in (profiles[0].remark or ""),
            )

        # 律师已代录同手机号档案时，注册应认领而不是重复建档
        r = await client.post(
            "/api/auth/register",
            json={
                "username": TEMP_CLIENT2,
                "password": TEMP_PASSWORD,
                "real_name": "流程核查客户二",
                "phone": TEMP_CLIENT2,
            },
        )
        check("已有代录档案时仍可注册", r.status_code in (200, 201), f"HTTP {r.status_code}")
        async with SessionLocal() as db:
            await db.rollback()
            rows2 = (
                (
                    await db.execute(
                        select(ClientProfile).where(ClientProfile.phone == TEMP_CLIENT2)
                    )
                )
                .scalars()
                .all()
            )
            user2 = await db.scalar(select(User).where(User.username == TEMP_CLIENT2))
            check("认领代录档案而非重复建档", len(rows2) == 1, f"{len(rows2)} 条")
            check(
                "认领后档案绑定新账号",
                len(rows2) == 1
                and user2 is not None
                and rows2[0].user_id == user2.id,
            )
            check(
                "认领不改动原有来源渠道",
                len(rows2) == 1 and rows2[0].source_channel == "转介绍",
                rows2[0].source_channel if rows2 else "缺失",
            )

        r = await client.post(
            "/api/auth/login", json={"username": TEMP_CLIENT, "password": TEMP_PASSWORD}
        )
        client_login = r.json() if r.status_code == 200 else {}
        check("注册后可立即登录（无需审核放行）", r.status_code == 200, f"HTTP {r.status_code}")
        client_token = client_login.get("access_token", "")
        check("登录返回 client 身份", client_login.get("user", {}).get("role") == "client")

        r = await client.get("/api/admin/users", headers=headers(client_token))
        check("客户访问账号管理被拒", r.status_code == 403, f"HTTP {r.status_code}")

        # 客户不走进内部案件管理，只走 /api/my/* 的自有数据接口
        r = await client.get("/api/cases", headers=headers(client_token))
        check("客户访问内部案件列表被拒", r.status_code == 403, f"HTTP {r.status_code}")

        r = await client.get("/api/my/cases", headers=headers(client_token))
        mine = r.json() if r.status_code == 200 else None
        check(
            "新注册客户可进入我的案件",
            r.status_code == 200,
            f"HTTP {r.status_code}",
        )
        check(
            "新注册客户无委托时案件列表为空（无越权）",
            isinstance(mine, list) and len(mine) == 0,
            f"{len(mine) if isinstance(mine, list) else 'N/A'} 条",
        )

        r = await client.post(
            "/api/admin/users/lawyers",
            headers=headers(client_token),
            json={"username": "__x__", "password": "123456", "real_name": "x"},
        )
        check("客户开通律师账号被拒", r.status_code == 403, f"HTTP {r.status_code}")

        r = await client.post(
            "/api/auth/register",
            json={"username": TEMP_CLIENT, "password": TEMP_PASSWORD, "real_name": "重复"},
        )
        check("重复手机号注册返回 409", r.status_code == 409, f"HTTP {r.status_code}")

        # ---------- 二、管理员开通律师 ----------
        print("\n二、管理员后台开通律师")
        r = await client.post(
            "/api/admin/users/lawyers",
            headers=headers(token),
            json={
                "username": TEMP_LAWYER,
                "password": TEMP_PASSWORD,
                "real_name": "流程核查律师",
                "phone": "13800000000",
            },
        )
        created = r.json() if r.status_code < 300 else {}
        check("开通成功", r.status_code in (200, 201), f"HTTP {r.status_code}")
        check("角色为 lawyer", created.get("role") == "lawyer", str(created.get("role")))
        check("初始状态启用", created.get("status") == 1, f"status={created.get('status')}")

        r = await client.post(
            "/api/admin/users/lawyers",
            headers=headers(token),
            json={"username": TEMP_LAWYER, "password": TEMP_PASSWORD, "real_name": "重复工号"},
        )
        check("重复工号返回 409", r.status_code == 409, f"HTTP {r.status_code}")

        r = await client.post(
            "/api/auth/login", json={"username": TEMP_LAWYER, "password": TEMP_PASSWORD}
        )
        lawyer_login = r.json() if r.status_code == 200 else {}
        check("新律师可登录", r.status_code == 200, f"HTTP {r.status_code}")
        lawyer_token = lawyer_login.get("access_token", "")

        r = await client.get("/api/stats/my", headers=headers(lawyer_token))
        check("律师可访问律师工作台数据", r.status_code == 200, f"HTTP {r.status_code}")

        r = await client.get("/api/admin/users", headers=headers(lawyer_token))
        check("律师访问账号管理被拒", r.status_code == 403, f"HTTP {r.status_code}")

        r = await client.get("/api/admin/logs", headers=headers(lawyer_token))
        check("律师访问操作日志被拒", r.status_code == 403, f"HTTP {r.status_code}")

        # ---------- 三、落库形态 ----------
        print("\n三、数据落库")
        async with SessionLocal() as db:
            await db.rollback()
            rows = (
                (
                    await db.execute(
                        select(User).where(
                            or_(User.username == TEMP_CLIENT, User.username == TEMP_LAWYER)
                        )
                    )
                )
                .scalars()
                .all()
            )
            by_name = {u.username: u for u in rows}
            check("客户账号在库中", TEMP_CLIENT in by_name)
            check(
                "客户账号无审核标记（status=1）",
                by_name.get(TEMP_CLIENT) is not None and by_name[TEMP_CLIENT].status == 1,
            )
            check("律师账号在库中", TEMP_LAWYER in by_name)

            log_count = len(
                (
                    await db.execute(
                        select(OperationLog.id).where(
                            OperationLog.action.in_(["register", "create_lawyer", "login"])
                        )
                    )
                )
                .scalars()
                .all()
            )
            check("注册/开通/登录均落审计日志", log_count > 0, f"{log_count} 条")

    await cleanup()


if __name__ == "__main__":
    asyncio.run(main())
    print()
    if FAILED:
        print(f"FAILED {len(FAILED)} 项: {', '.join(FAILED)}")
        sys.exit(1)
    print("全部通过")

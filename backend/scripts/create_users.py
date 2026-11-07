"""创建/重置三种角色的种子账号。

对应任务拆解 11.1.7（初始化脚本）与 1.3.3（三个测试账号验收）。

密码来源：**环境变量优先**，未设置时回落到仅用于本地开发的默认值。
生产环境（APP_ENV=prod）必须提供环境变量且长度 >= 12，否则拒绝执行——
这样代码仓库里不会存在任何「生产有效」的口令。

已存在账号的处理分环境：

- 开发（APP_ENV=dev）：直接重置为期望密码，便于反复联调（与历史行为一致）；
- 生产（APP_ENV=prod）：默认跳过，必须显式加 ``--reset`` 才会改密码，
  避免误跑一次把所有账号口令重置掉。

用法：
    cd backend
    uv run python scripts/create_users.py          # 创建缺失账号（生产下跳过已存在）
    uv run python scripts/create_users.py --reset  # 已存在账号也重置密码
    uv run python scripts/create_users.py --list   # 只查看现有账号，不写入

说明：`tianting` 是唯一的管理员账号。本脚本会清理 schema.sql 早期种子
产出的旧 `admin` 账号（连同其审计日志），确保管理员账号唯一。
"""

import asyncio
import os
import sys
from pathlib import Path

# 保证能 import 到 app 包（直接以脚本方式运行时，sys.path 不含 backend/）
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import delete, select

from app.config import settings
from app.core.security import hash_password
from app.database import SessionLocal, dispose_engine
from app.models.log import OperationLog
from app.models.user import User

# 待创建的账号：username 使用姓名拼音，作为登录账号。
# ``dev_password`` 只在 APP_ENV=dev 下生效；生产从 ``password_env`` 指定的
# 环境变量取值，未设置则脚本拒绝执行（见 _resolve_password）。
SEED_USERS = [
    {
        "username": "bainingbing",
        "real_name": "白凝冰",
        "dev_password": "bnb123456",
        "password_env": "SEED_CLIENT_PASSWORD",
        "role": "client",
        "phone": "13900003001",
        "email": "bainingbing@example.com",
    },
    {
        "username": "guyuefangyuan",
        "real_name": "古月方源",
        "dev_password": "gyfy3951",
        "password_env": "SEED_LAWYER_PASSWORD",
        "role": "lawyer",
        "phone": "13900003002",
        "email": "guyuefangyuan@example.com",
    },
    {
        "username": "tianting",
        "real_name": "天庭",
        "dev_password": "admin",
        "password_env": "SEED_ADMIN_PASSWORD",
        "role": "admin",
        "phone": "13900003003",
        "email": "tianting@example.com",
    },
]

# schema.sql 早期种子账号，需清理（tianting 是唯一管理员）
LEGACY_ADMIN_USERNAME = "admin"

# 生产环境密码最短长度：低于此值视为弱口令，直接拒绝
MIN_PROD_PASSWORD_LEN = 12


def _resolve_password(item: dict[str, str], strict: bool) -> str:
    """取账号密码：环境变量优先，开发环境回落到内置默认值。

    ``strict=True``（APP_ENV=prod）时要求必须显式配置且足够强，
    避免把开发弱口令带上生产。
    """
    env_name = item["password_env"]
    value = os.getenv(env_name, "").strip()
    if value:
        if strict and value == item["dev_password"]:
            raise SystemExit(
                f"{env_name} 不能沿用开发默认密码，请换成长度 >= "
                f"{MIN_PROD_PASSWORD_LEN} 位的强密码"
            )
        if strict and len(value) < MIN_PROD_PASSWORD_LEN:
            raise SystemExit(
                f"{env_name} 长度不足 {MIN_PROD_PASSWORD_LEN} 位，生产环境请使用强密码"
            )
        return value
    if strict:
        raise SystemExit(
            f"生产环境必须设置 {env_name}（长度 >= {MIN_PROD_PASSWORD_LEN} 位）；"
            "脚本不会在生产环境使用内置的开发默认密码"
        )
    return item["dev_password"]


def _mask(password: str) -> str:
    """生产环境不把口令明文打到终端/部署日志里。"""
    return f"***（长度 {len(password)}）" if password else "***"


async def list_users() -> None:
    """列出数据库中的全部账号。"""
    async with SessionLocal() as db:
        rows = (
            await db.execute(
                select(
                    User.id,
                    User.username,
                    User.real_name,
                    User.role,
                    User.status,
                    User.created_at,
                ).order_by(User.id)
            )
        ).all()

    print(f"{'ID':>4}  {'账号':<16}{'姓名':<12}{'角色':<8}{'状态':<6}创建时间")
    print("-" * 72)
    for uid, username, real_name, role, status, created_at in rows:
        state = "正常" if status == 1 else "禁用"
        print(f"{uid:>4}  {username:<16}{real_name:<12}{role:<8}{state:<6}{created_at}")
    print(f"\n共 {len(rows)} 个账号")


async def cleanup_legacy_admin(db) -> None:
    """删除早期 schema.sql 种子的旧 admin 账号，确保管理员唯一。"""
    legacy = await db.scalar(
        select(User).where(User.username == LEGACY_ADMIN_USERNAME)
    )
    if legacy is None:
        return
    # 先删其审计日志（外键引用），再删账号
    await db.execute(delete(OperationLog).where(OperationLog.user_id == legacy.id))
    await db.delete(legacy)
    await db.commit()
    print(f"  [清理] 删除旧管理员账号 {LEGACY_ADMIN_USERNAME}（id={legacy.id}）及其审计日志")


async def create_users(reset: bool = False) -> None:
    """创建种子账号；已存在的账号按环境决定是否重置密码。

    - 开发：默认重置（与历史行为一致，方便反复联调）；
    - 生产：默认跳过，只有 ``--reset`` 才改密码，防止误跑覆盖线上口令。
    """
    strict = settings.app_env == "prod"
    plan = [
        {**item, "password": _resolve_password(item, strict)} for item in SEED_USERS
    ]

    async with SessionLocal() as db:
        await cleanup_legacy_admin(db)

        for item in plan:
            username = item["username"]
            user = await db.scalar(select(User).where(User.username == username))

            if user is None:
                user = User(
                    username=username,
                    password_hash=hash_password(item["password"]),
                    real_name=item["real_name"],
                    role=item["role"],
                    phone=item["phone"],
                    email=item["email"],
                    status=1,
                )
                db.add(user)
                action = "创建"
            elif reset or not strict:
                # 开发环境或显式 --reset：重置密码、角色与状态
                user.password_hash = hash_password(item["password"])
                user.real_name = item["real_name"]
                user.role = item["role"]
                user.phone = item["phone"]
                user.email = item["email"]
                user.status = 1
                action = "重置"
            else:
                print(
                    f"  [跳过] {item['role']:<7} 账号 {username:<16} "
                    "已存在（需要改密码请加 --reset）"
                )
                continue

            await db.commit()
            shown = _mask(item["password"]) if strict else item["password"]
            print(
                f"  [{action}] {item['role']:<7} "
                f"{item['real_name']:<10}账号 {username:<16}密码 {shown}"
            )

    print("\n完成。登录地址：POST /api/auth/login")


async def main() -> None:
    try:
        if "--list" in sys.argv:
            await list_users()
        else:
            await create_users(reset="--reset" in sys.argv)
    finally:
        await dispose_engine()


if __name__ == "__main__":
    asyncio.run(main())

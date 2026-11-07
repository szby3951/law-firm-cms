"""历史数据回填：把 client_profile.user_id 按手机号关联到客户登录账号。

背景：
- 律师代录客户档案时未关联登录账号，导致客户端「我的案件」查不到案件。
- 本脚本按手机号把 client_profile 匹配到 role=client 的账号，回填 user_id。

用法（幂等，可重复执行）：
    uv run python scripts/backfill_client_user.py
    uv run python scripts/backfill_client_user.py --dry-run   # 只预览不写入
"""

import argparse
import asyncio
import sys

sys.path.insert(0, ".")

from sqlalchemy import select

from app.database import SessionLocal, dispose_engine
from app.models.client import ClientProfile
from app.models.user import User


async def main(dry_run: bool) -> None:
    async with SessionLocal() as db:
        # 所有 client 账号，按手机号建索引
        users = (
            (
                await db.execute(
                    select(User).where(User.role == "client", User.phone.is_not(None))
                )
            )
            .scalars()
            .all()
        )
        by_phone = {u.phone: u for u in users}

        # 所有 user_id 为空的档案
        profiles = (
            (
                await db.execute(
                    select(ClientProfile).where(ClientProfile.user_id.is_(None))
                )
            )
            .scalars()
            .all()
        )

        matched = 0
        unmatched = 0
        for p in profiles:
            if not p.phone:
                unmatched += 1
                continue
            u = by_phone.get(p.phone)
            if u is None:
                unmatched += 1
                continue
            if not dry_run:
                p.user_id = u.id
            matched += 1
            print(
                f"[{'预览' if dry_run else '回填'}] 档案 id={p.id} name={p.name!r} "
                f"phone={p.phone} → 账号 {u.username}（{u.real_name}）user_id={u.id}"
            )

        if not dry_run:
            await db.commit()

        print("-" * 60)
        print(f"客户账号数（有手机号）: {len(by_phone)}")
        print(f"待回填档案数（user_id 为空）: {len(profiles)}")
        print(f"匹配成功: {matched}  未匹配: {unmatched}")
        if dry_run:
            print("（dry-run 模式，未写入数据库）")

    await dispose_engine()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="回填客户档案与登录账号的关联")
    parser.add_argument("--dry-run", action="store_true", help="只预览不写入")
    args = parser.parse_args()
    asyncio.run(main(args.dry_run))

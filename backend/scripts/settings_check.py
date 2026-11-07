"""模块 11.1 系统设置核查：字典 CRUD、律所信息、AI 配置生效与回滚、权限。

用法::

    cd backend
    .venv/Scripts/python.exe scripts/settings_check.py --base http://127.0.0.1:8000

要点：
- 用库里首个启用账号签发三种角色令牌，不改动任何既有账号密码；
- 走真实 HTTP，同时用原生 SQL 交叉核对落库结果；
- 字典测试项以 ``check_`` 前缀建、结束时删除；
- AI 配置测试会临时写入 Key 并启用，结束时按测试前快照**还原**，
  保证服务进程回滚到 .env 配置；
- 本脚本产生的审计日志一并清理，库恢复原状。
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
from app.models.dict import DictItem
from app.models.log import OperationLog
from app.models.setting import AIConfig, FirmInfo
from app.models.user import User

BASE = "http://127.0.0.1:8000"
FAILED: list[str] = []
TEST_TYPE = "check_settings"
TEST_VALUE = "check_value"
TEST_KEY = "sk-settings-check-0123456789abcdef"


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"  [{'OK  ' if ok else 'FAIL'}] {name}{(' — ' + detail) if detail else ''}")
    if not ok:
        FAILED.append(name)


def headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def pick_token(db, role: str) -> str:
    user = await db.scalar(
        select(User).where(User.role == role, User.status == 1).order_by(User.id.asc())
    )
    if user is None:
        raise SystemExit(f"库中没有可用的 {role} 账号")
    return create_access_token(user.id, user.role)


async def snapshot(db) -> dict[str, object]:
    """记录测试前的律所信息与 AI 配置，便于还原。"""
    firm = await db.scalar(select(FirmInfo).order_by(FirmInfo.id.asc()))
    ai = await db.scalar(select(AIConfig).order_by(AIConfig.id.asc()))
    return {
        "firm": (
            {
                "name": firm.name,
                "logo": firm.logo,
                "address": firm.address,
                "phone": firm.phone,
                "intro": firm.intro,
            }
            if firm
            else None
        ),
        "ai": (
            {
                "provider": ai.provider,
                "base_url": ai.base_url,
                "model": ai.model,
                "temperature": ai.temperature,
                "embedding_model": ai.embedding_model,
                "api_key": ai.api_key,
                "status": ai.status,
            }
            if ai
            else None
        ),
        "max_log_id": int(await db.scalar(select(func.max(OperationLog.id))) or 0),
    }


async def cleanup(db, snap: dict[str, object]) -> None:
    """删除临时字典项、本脚本写入的审计日志，并还原律所与 AI 配置。"""
    # 临时字典
    ids = (
        (await db.execute(select(DictItem.id).where(DictItem.dict_type == TEST_TYPE)))
        .scalars()
        .all()
    )
    if ids:
        await db.execute(delete(DictItem).where(DictItem.id.in_(ids)))

    # 脚本行为产生的日志
    await db.execute(
        delete(OperationLog).where(
            OperationLog.id > int(snap["max_log_id"]),
            OperationLog.target.like("dict:%")
            | OperationLog.target.in_(["firm:1", "ai_config:1"]),
        )
    )

    firm_snap = snap["firm"]
    if firm_snap:
        firm = await db.scalar(select(FirmInfo).order_by(FirmInfo.id.asc()))
        if firm is not None:
            for field, value in firm_snap.items():
                setattr(firm, field, value)

    ai_snap = snap["ai"]
    if ai_snap:
        ai = await db.scalar(select(AIConfig).order_by(AIConfig.id.asc()))
        if ai is not None:
            for field, value in ai_snap.items():
                setattr(ai, field, value)

    await db.commit()


async def main() -> None:
    parser = argparse.ArgumentParser(description="模块 11.1 系统设置核查")
    parser.add_argument("--base", default=BASE, help="后端地址")
    args = parser.parse_args()
    base = args.base.rstrip("/")

    async with SessionLocal() as db:
        admin_tok = await pick_token(db, "admin")
        lawyer_tok = await pick_token(db, "lawyer")
        client_tok = await pick_token(db, "client")
        snap = await snapshot(db)
        await cleanup(db, snap)  # 上次异常退出的残留

        async with httpx.AsyncClient(base_url=base, timeout=20) as http:
            # ---------------------------------------------------------- 权限
            print("\n== 权限隔离 ==")
            for path in ("/api/admin/dicts", "/api/admin/firm", "/api/admin/ai-config"):
                r = await http.get(path)
                check(f"未登录访问 {path} 401", r.status_code == 401, f"HTTP {r.status_code}")
                r = await http.get(path, headers=headers(lawyer_tok))
                check(f"律师访问 {path} 403", r.status_code == 403, f"HTTP {r.status_code}")
                r = await http.get(path, headers=headers(client_tok))
                check(f"客户访问 {path} 403", r.status_code == 403, f"HTTP {r.status_code}")

            # ---------------------------------------------------------- 字典读
            print("\n== 字典列表 ==")
            r = await http.get("/api/admin/dicts", headers=headers(admin_tok))
            check("管理员可读字典列表", r.status_code == 200, f"HTTP {r.status_code}")
            body = r.json() if r.status_code == 200 else {}
            types = body.get("types") or []
            total_sql = int(
                await db.scalar(
                    select(func.count()).select_from(DictItem).where(DictItem.dict_type != TEST_TYPE)
                )
                or 0
            )
            check(
                "分类汇总与库中条目数一致",
                sum(t["count"] for t in types if t["dict_type"] != TEST_TYPE) == total_sql,
                f"{sum(t['count'] for t in types if t['dict_type'] != TEST_TYPE)} vs {total_sql}",
            )
            first_type = types[0]["dict_type"] if types else None
            r = await http.get(
                "/api/admin/dicts",
                params={"dict_type": first_type},
                headers=headers(admin_tok),
            )
            only = r.json().get("items", []) if r.status_code == 200 else []
            check(
                f"按分类过滤只返回 {first_type}",
                r.status_code == 200 and only and all(i["dict_type"] == first_type for i in only),
                f"{len(only)} 条",
            )
            check(
                "字典项按 sort 升序",
                [i["sort"] for i in only] == sorted(i["sort"] for i in only),
            )

            # ---------------------------------------------------------- 字典写
            print("\n== 字典增改删 ==")
            r = await http.post(
                "/api/admin/dicts",
                json={"dict_type": TEST_TYPE, "label": "核查项", "value": TEST_VALUE, "sort": 10},
                headers=headers(admin_tok),
            )
            check("新增字典项 201", r.status_code == 201, f"HTTP {r.status_code}")
            item = r.json() if r.status_code == 201 else {}
            item_id = item.get("id")

            r = await http.post(
                "/api/admin/dicts",
                json={"dict_type": TEST_TYPE, "label": "重复", "value": TEST_VALUE, "sort": 20},
                headers=headers(admin_tok),
            )
            check("同分类重复取值 409", r.status_code == 409, f"HTTP {r.status_code}")

            r = await http.post(
                "/api/admin/dicts",
                json={"dict_type": TEST_TYPE, "label": "非法", "value": "含 空格", "sort": 30},
                headers=headers(admin_tok),
            )
            check("存储值含空格被拒 422", r.status_code == 422, f"HTTP {r.status_code}")

            r = await http.post(
                "/api/admin/dicts",
                json={"dict_type": "Bad-Type", "label": "非法", "value": "ok_value", "sort": 30},
                headers=headers(admin_tok),
            )
            check("分类命名非法被拒 422", r.status_code == 422, f"HTTP {r.status_code}")

            r = await http.put(
                f"/api/admin/dicts/{item_id}",
                json={"dict_type": TEST_TYPE, "label": "核查项-改", "value": TEST_VALUE, "sort": 5},
                headers=headers(admin_tok),
            )
            check(
                "修改字典项 200 且字段生效",
                r.status_code == 200
                and r.json().get("label") == "核查项-改"
                and r.json().get("sort") == 5,
                f"HTTP {r.status_code}",
            )
            await db.rollback()
            row = await db.get(DictItem, item_id)
            check(
                "修改已落库",
                row is not None and row.label == "核查项-改" and row.sort == 5,
                f"{row.label if row else '缺失'} / {row.sort if row else '-'}",
            )

            r = await http.put(
                "/api/admin/dicts/99999999",
                json={"dict_type": TEST_TYPE, "label": "x", "value": "x_value", "sort": 0},
                headers=headers(admin_tok),
            )
            check("修改不存在的字典项 404", r.status_code == 404, f"HTTP {r.status_code}")

            # ---------------------------------------------------------- 律所信息
            print("\n== 律所信息 ==")
            r = await http.get("/api/admin/firm", headers=headers(admin_tok))
            check("读取律所信息 200", r.status_code == 200, f"HTTP {r.status_code}")
            firm0 = r.json() if r.status_code == 200 else {}
            check("律所名称非空", bool(firm0.get("name")), str(firm0.get("name")))

            r = await http.put(
                "/api/admin/firm",
                json={"name": "", "address": None, "phone": None, "intro": None},
                headers=headers(admin_tok),
            )
            check("空律所名称被拒 422", r.status_code == 422, f"HTTP {r.status_code}")

            payload = {
                "name": "核查临时律所",
                "logo": None,
                "address": "核查地址",
                "phone": "010-12345678",
                "intro": "仅用于自动化核查，结束即还原",
            }
            r = await http.put("/api/admin/firm", json=payload, headers=headers(admin_tok))
            check("保存律所信息 200", r.status_code == 200, f"HTTP {r.status_code}")
            saved = r.json() if r.status_code == 200 else {}
            check(
                "保存结果回显正确",
                saved.get("name") == payload["name"]
                and saved.get("address") == payload["address"]
                and saved.get("phone") == payload["phone"],
            )
            r = await http.get("/api/admin/firm", headers=headers(admin_tok))
            check(
                "再次读取为修改后的值",
                r.status_code == 200 and r.json().get("name") == payload["name"],
            )
            await db.rollback()
            firm_row = await db.scalar(select(FirmInfo).order_by(FirmInfo.id.asc()))
            check(
                "律所信息已落库",
                firm_row is not None and firm_row.name == payload["name"],
                firm_row.name if firm_row else "缺失",
            )

            # ---------------------------------------------------------- AI 配置
            print("\n== AI 配置 ==")
            r = await http.get("/api/admin/ai-config", headers=headers(admin_tok))
            check("读取 AI 配置 200", r.status_code == 200, f"HTTP {r.status_code}")
            ai0 = r.json() if r.status_code == 200 else {}
            check(
                "返回环境模型与生效来源",
                bool(ai0.get("env_model")) and ai0.get("active_source") in ("env", "db"),
                f"{ai0.get('env_model')} / {ai0.get('active_source')}",
            )
            check(
                "初始状态 Key 未配置时脱敏串为空",
                ai0.get("api_key_set") is not False or ai0.get("api_key_masked") == "",
            )

            base_payload = {
                "provider": ai0.get("provider") or "deepseek",
                "base_url": ai0.get("base_url") or "https://api.deepseek.com/v1",
                "model": ai0.get("model") or "deepseek-chat",
                "temperature": 0.3,
                "embedding_model": ai0.get("embedding_model"),
            }

            if not ai0.get("api_key_set"):
                r = await http.put(
                    "/api/admin/ai-config",
                    json={**base_payload, "api_key": None, "status": 1},
                    headers=headers(admin_tok),
                )
                check("无 Key 时启用被拒 400", r.status_code == 400, f"HTTP {r.status_code}")

            r = await http.put(
                "/api/admin/ai-config",
                json={**base_payload, "base_url": "api.deepseek.com", "status": 0},
                headers=headers(admin_tok),
            )
            check("接口地址缺协议被拒 422", r.status_code == 422, f"HTTP {r.status_code}")

            r = await http.put(
                "/api/admin/ai-config",
                json={**base_payload, "temperature": 5, "status": 0},
                headers=headers(admin_tok),
            )
            check("温度越界被拒 422", r.status_code == 422, f"HTTP {r.status_code}")

            r = await http.put(
                "/api/admin/ai-config",
                json={
                    **base_payload,
                    "model": "settings-check-model",
                    "api_key": TEST_KEY,
                    "status": 1,
                },
                headers=headers(admin_tok),
            )
            check("启用数据库配置 200", r.status_code == 200, f"HTTP {r.status_code}")
            ai1 = r.json() if r.status_code == 200 else {}
            check(
                "生效来源切换为 db",
                ai1.get("active_source") == "db",
                str(ai1.get("active_source")),
            )
            check(
                "生效模型为数据库中的模型",
                ai1.get("active_model") == "settings-check-model",
                str(ai1.get("active_model")),
            )
            check("Key 已置为已配置", ai1.get("api_key_set") is True)
            check(
                "Key 只回脱敏串",
                ai1.get("api_key_masked") == f"{TEST_KEY[:4]}******{TEST_KEY[-4:]}",
                str(ai1.get("api_key_masked")),
            )
            check("响应体不含明文 Key", TEST_KEY not in r.text)

            r = await http.get("/api/admin/ai-config", headers=headers(admin_tok))
            check(
                "再次读取仍为数据库配置",
                r.status_code == 200 and r.json().get("active_source") == "db",
            )

            r = await http.put(
                "/api/admin/ai-config",
                json={**base_payload, "model": "settings-check-model", "status": 0},
                headers=headers(admin_tok),
            )
            ai2 = r.json() if r.status_code == 200 else {}
            check(
                "关闭后回滚到 .env",
                r.status_code == 200
                and ai2.get("active_source") == "env"
                and ai2.get("active_model") == ai2.get("env_model"),
                f"{ai2.get('active_source')} / {ai2.get('active_model')} vs {ai2.get('env_model')}",
            )
            check(
                "关闭后 Key 仍保留（便于下次启用）",
                ai2.get("api_key_set") is True,
            )

            # ---------------------------------------------------------- 审计
            print("\n== 审计留痕 ==")
            await db.rollback()
            log_count = int(
                await db.scalar(
                    select(func.count())
                    .select_from(OperationLog)
                    .where(OperationLog.id > int(snap["max_log_id"]))
                )
                or 0
            )
            check("设置变更写入审计日志", log_count >= 5, f"{log_count} 条")
            targets = (
                (
                    await db.execute(
                        select(OperationLog.target).where(
                            OperationLog.id > int(snap["max_log_id"])
                        )
                    )
                )
                .scalars()
                .all()
            )
            check(
                "覆盖字典、律所、AI 三类目标",
                any(t and t.startswith("dict:") for t in targets)
                and "firm:1" in targets
                and "ai_config:1" in targets,
            )

        # ---------------------------------------------------------- 清理
        print("\n== 还原现场 ==")
        await db.rollback()
        await cleanup(db, snap)
        await db.rollback()

        remain = int(
            await db.scalar(
                select(func.count()).select_from(DictItem).where(DictItem.dict_type == TEST_TYPE)
            )
            or 0
        )
        check("临时字典项已清理", remain == 0, f"残留 {remain} 条")

        firm_now = await db.scalar(select(FirmInfo).order_by(FirmInfo.id.asc()))
        firm_snap = snap["firm"] or {}
        check(
            "律所信息已还原",
            firm_now is not None and firm_now.name == firm_snap.get("name"),
            firm_now.name if firm_now else "缺失",
        )

        ai_now = await db.scalar(select(AIConfig).order_by(AIConfig.id.asc()))
        ai_snap = snap["ai"] or {}
        check(
            "AI 配置已还原",
            ai_now is not None
            and ai_now.model == ai_snap.get("model")
            and ai_now.status == ai_snap.get("status")
            and ai_now.api_key == ai_snap.get("api_key"),
            f"model={ai_now.model if ai_now else '-'} status={ai_now.status if ai_now else '-'}",
        )

        logs_left = int(
            await db.scalar(
                select(func.count())
                .select_from(OperationLog)
                .where(OperationLog.id > int(snap["max_log_id"]))
            )
            or 0
        )
        check("脚本写入的审计日志已清理", logs_left == 0, f"残留 {logs_left} 条")

    print()
    if FAILED:
        print(f"FAILED {len(FAILED)} 项：")
        for name in FAILED:
            print(f"  - {name}")
        raise SystemExit(1)
    print("全部断言通过")


if __name__ == "__main__":
    asyncio.run(main())

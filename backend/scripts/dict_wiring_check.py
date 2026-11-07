"""模块 11.3.1 核查：字典改动是否真的传到业务端（下拉候选 + 显示标签）。

用法::

    cd backend
    .venv/Scripts/python.exe scripts/dict_wiring_check.py --base http://127.0.0.1:8000

覆盖：
1. ``GET /api/dicts`` 三类角色都能读、未登录 401；
2. 新增/改名/删除字典项后，候选接口立刻反映（运行期缓存已刷新）；
3. 改 ``doc_type`` 的中文名后，文书列表的 ``doc_type_label`` 立即跟着变；
4. 结束把改动全部还原，库与缓存回到测试前状态。
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
from app.models.user import User

BASE = "http://127.0.0.1:8000"
FAILED: list[str] = []
TEST_TYPE = "check_wiring"
TEST_VALUE = "wiring_value"
TEMP_LABEL = "起诉状-核查"


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


async def cleanup(db) -> None:
    """删掉测试字典项与脚本产生的审计日志。"""
    ids = (
        (await db.execute(select(DictItem.id).where(DictItem.dict_type == TEST_TYPE)))
        .scalars()
        .all()
    )
    if ids:
        await db.execute(delete(OperationLog).where(OperationLog.target.in_([f"dict:{i}" for i in ids])))
        await db.execute(delete(DictItem).where(DictItem.id.in_(ids)))
        await db.commit()


async def main() -> None:
    parser = argparse.ArgumentParser(description="字典接线核查")
    parser.add_argument("--base", default=BASE)
    args = parser.parse_args()
    base = args.base.rstrip("/")

    async with SessionLocal() as db:
        admin_tok = await pick_token(db, "admin")
        lawyer_tok = await pick_token(db, "lawyer")
        client_tok = await pick_token(db, "client")
        await cleanup(db)  # 上次异常退出的残留

        doc_item = await db.scalar(
            select(DictItem).where(
                DictItem.dict_type == "doc_type", DictItem.value == "complaint"
            )
        )
        if doc_item is None:
            raise SystemExit("库中缺少 doc_type/complaint 字典项，无法验证标签联动")
        origin_doc_label = doc_item.label
        doc_item_id = doc_item.id
        start_log_id = int(
            await db.scalar(select(func.max(OperationLog.id))) or 0
        )

        temp_item_id: int | None = None
        try:
            async with httpx.AsyncClient(base_url=base, timeout=20) as http:
                # ------------------------------------------------ 读权限
                print("\n== 候选读取权限 ==")
                r = await http.get("/api/dicts")
                check("未登录读取字典 401", r.status_code == 401, f"HTTP {r.status_code}")
                for role, tok in (("管理员", admin_tok), ("律师", lawyer_tok), ("客户", client_tok)):
                    r = await http.get("/api/dicts", headers=headers(tok))
                    body = r.json() if r.status_code == 200 else {}
                    check(
                        f"{role}可读字典候选",
                        r.status_code == 200 and "case_cause" in (body.get("dicts") or {}),
                        f"HTTP {r.status_code}",
                    )
                payload = body.get("dicts") or {}
                check(
                    "候选覆盖四类业务字典",
                    {"case_cause", "contract_type", "doc_type", "source_channel"}
                    <= set(payload.keys()),
                    "、".join(sorted(payload.keys())),
                )
                check(
                    "候选按排序返回且带标签",
                    all(o.get("label") and o.get("value") for o in payload.get("doc_type", [])),
                )

                # ------------------------------------------------ 增改删联动
                print("\n== 字典改动的联动 ==")
                r = await http.post(
                    "/api/admin/dicts",
                    json={
                        "dict_type": TEST_TYPE,
                        "label": "接线核查项",
                        "value": TEST_VALUE,
                        "sort": 10,
                    },
                    headers=headers(admin_tok),
                )
                check("新增字典项 201", r.status_code == 201, f"HTTP {r.status_code}")
                temp_item_id = (r.json() or {}).get("id")

                r = await http.get("/api/dicts", headers=headers(lawyer_tok))
                items = (r.json().get("dicts") or {}).get(TEST_TYPE) or []
                check(
                    "新增后候选立即可见（无需重启）",
                    any(i["value"] == TEST_VALUE for i in items),
                    f"{len(items)} 条",
                )

                r = await http.put(
                    f"/api/admin/dicts/{temp_item_id}",
                    json={
                        "dict_type": TEST_TYPE,
                        "label": "接线核查项-改名",
                        "value": TEST_VALUE,
                        "sort": 10,
                    },
                    headers=headers(admin_tok),
                )
                check("改名 200", r.status_code == 200, f"HTTP {r.status_code}")
                r = await http.get("/api/dicts", headers=headers(lawyer_tok))
                items = (r.json().get("dicts") or {}).get(TEST_TYPE) or []
                check(
                    "改名后候选标签同步",
                    bool(items) and items[0]["label"] == "接线核查项-改名",
                    items[0]["label"] if items else "缺失",
                )

                # ------------------------------------------------ 文书标签联动
                print("\n== 显示标签联动（doc_type）==")
                r = await http.put(
                    f"/api/admin/dicts/{doc_item_id}",
                    json={
                        "dict_type": "doc_type",
                        "label": TEMP_LABEL,
                        "value": "complaint",
                        "sort": 10,
                    },
                    headers=headers(admin_tok),
                )
                check("临时改文书类型中文名 200", r.status_code == 200, f"HTTP {r.status_code}")

                r = await http.get(
                    "/api/documents", params={"page_size": 5}, headers=headers(admin_tok)
                )
                docs = r.json().get("items", []) if r.status_code == 200 else []
                complaint = [d for d in docs if d["doc_type"] == "complaint"]
                check(
                    "文书列表的 doc_type_label 跟着字典变",
                    bool(complaint) and complaint[0]["doc_type_label"] == TEMP_LABEL,
                    complaint[0]["doc_type_label"] if complaint else "无 complaint 文书",
                )
                check(
                    "存储值不受影响（仍是编码）",
                    bool(complaint) and complaint[0]["doc_type"] == "complaint",
                )

                # 还原
                r = await http.put(
                    f"/api/admin/dicts/{doc_item_id}",
                    json={
                        "dict_type": "doc_type",
                        "label": origin_doc_label,
                        "value": "complaint",
                        "sort": 10,
                    },
                    headers=headers(admin_tok),
                )
                check("还原文书类型中文名 200", r.status_code == 200, f"HTTP {r.status_code}")
                r = await http.get(
                    "/api/documents", params={"page_size": 5}, headers=headers(admin_tok)
                )
                docs = r.json().get("items", []) if r.status_code == 200 else []
                complaint = [d for d in docs if d["doc_type"] == "complaint"]
                check(
                    "还原后标签回到原文",
                    bool(complaint) and complaint[0]["doc_type_label"] == origin_doc_label,
                    complaint[0]["doc_type_label"] if complaint else "无 complaint 文书",
                )

                # ------------------------------------------------ 删除
                print("\n== 删除联动 ==")
                r = await http.delete(
                    f"/api/admin/dicts/{temp_item_id}", headers=headers(admin_tok)
                )
                check("删除字典项 204", r.status_code == 204, f"HTTP {r.status_code}")
                r = await http.get("/api/dicts", headers=headers(lawyer_tok))
                items = (r.json().get("dicts") or {}).get(TEST_TYPE) or []
                check("删除后候选立即消失", not items, f"{len(items)} 条")
                temp_item_id = None
        finally:
            # 异常时也要还原标签与临时项
            if temp_item_id is not None:
                await db.execute(delete(DictItem).where(DictItem.id == temp_item_id))
            row = await db.get(DictItem, doc_item_id)
            if row is not None and row.label != origin_doc_label:
                row.label = origin_doc_label
            await db.execute(
                delete(OperationLog).where(
                    OperationLog.id > start_log_id,
                    OperationLog.target.like("dict:%"),
                )
            )
            await db.commit()
            await cleanup(db)

        # 现场核对
        await db.rollback()
        left = (
            (await db.execute(select(DictItem.id).where(DictItem.dict_type == TEST_TYPE)))
            .scalars()
            .all()
        )
        check("临时字典项已清理", not left, f"残留 {len(left)} 条")
        row = await db.get(DictItem, doc_item_id)
        check(
            "文书类型标签已还原",
            row is not None and row.label == origin_doc_label,
            row.label if row else "缺失",
        )

    print()
    if FAILED:
        print(f"FAILED {len(FAILED)} 项：")
        for name in FAILED:
            print(f"  - {name}")
        raise SystemExit(1)
    print("全部断言通过")


if __name__ == "__main__":
    asyncio.run(main())

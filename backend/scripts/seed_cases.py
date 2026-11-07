"""为指定客户批量提交立案（归属律师：古月方源）。

对应「提交立案」数据填充需求。脚本幂等：同名案件已存在则跳过，
避免重复立案；案号由服务层自动生成（LF + 年月 + 序号），无需手动指定。

四个目标客户（已在 client_profile 表中存在，均归属古月方源律师）：
- 邓丽（个人，女）
- 嘉禾物流运输集团有限公司（机构）
- 郑鹏（个人，男）
- 肖雨（个人，女）

案件数据为相对真实的模拟数据（真实案由、法院、对方当事人、标的额、案情描述）。

用法：
    cd backend
    uv run python scripts/seed_cases.py          # 提交立案（幂等）
    uv run python scripts/seed_cases.py --list   # 只查看古月方源名下现有案件，不写入
"""

import asyncio
import sys
from pathlib import Path

# 保证能 import 到 app 包
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select

from app.database import SessionLocal, dispose_engine
from app.models.case import Case
from app.models.client import ClientProfile
from app.models.user import User
from app.schemas.case import CaseCreate
from app.services import case_service

# 律师账号（立案人 + 默认主办律师）
LAWYER_USERNAME = "guyuefangyuan"

# ---------------------------------------------------------------------------
# 四个目标客户：姓名 → 案件信息
# client 在库中的姓名精确匹配；机构客户（嘉禾物流）单独标注类型。
# ---------------------------------------------------------------------------
CASES = [
    {
        "client_name": "邓丽",
        "title": "邓丽与张伟离婚后财产分割纠纷案",
        "case_cause": "离婚纠纷",
        "case_type": "litigation",
        "court": "厦门市思明区人民法院",
        "opposing_party": "张伟",
        "amount": "1860000.00",
        "description": (
            "当事人邓丽与张伟于2021年登记离婚，双方对婚后共同购置的位于厦门市思明区"
            "房产一套及共同存款、车辆等财产分割产生争议。邓丽主张按双方约定对房产进行"
            "折价分割并取得相应补偿款，张伟拒绝配合办理过户及支付补偿，遂委托本所代理"
            "提起离婚后财产分割之诉。"
        ),
    },
    {
        "client_name": "嘉禾物流运输集团有限公司",
        "title": "嘉禾物流与恒通供应链公司运输合同纠纷案",
        "case_cause": "运输合同纠纷",
        "case_type": "litigation",
        "court": "上海市浦东新区人民法院",
        "opposing_party": "上海恒通供应链管理有限公司",
        "amount": "2350000.00",
        "description": (
            "嘉禾物流与恒通供应链于2025年签订公路货物运输合同，约定由嘉禾物流承接"
            "华东区域多批次货物运输。恒通供应链累计拖欠运费及逾期违约金共计人民币"
            "235万元，经多次催告仍未支付，嘉禾物流委托本所代理追索运费、违约金及相应"
            "利息。"
        ),
    },
    {
        "client_name": "郑鹏",
        "title": "郑鹏与青岛海纳制造公司工伤保险待遇纠纷案",
        "case_cause": "劳动争议",
        "case_type": "litigation",
        "court": "青岛市市南区人民法院",
        "opposing_party": "青岛海纳精密制造有限公司",
        "amount": "680000.00",
        "description": (
            "郑鹏系青岛海纳精密制造有限公司操作工，2025年11月在工作期间因设备故障"
            "受伤，经认定为工伤、伤残等级八级。公司未依法足额缴纳工伤保险，亦未支付"
            "停工留薪期工资及一次性伤残补助金等费用，郑鹏委托本所申请劳动仲裁并主张"
            "各项工伤保险待遇合计68万元。"
        ),
    },
    {
        "client_name": "肖雨",
        "title": "肖雨与林志强民间借贷纠纷案",
        "case_cause": "民间借贷纠纷",
        "case_type": "litigation",
        "court": "厦门市思明区人民法院",
        "opposing_party": "林志强",
        "amount": "520000.00",
        "description": (
            "林志强因经营周转需要，于2024年向肖雨分两次借款共计人民币52万元，约定"
            "年利率及还款期限。借款到期后林志强以经营困难为由长期拖延，仅归还少量利息。"
            "肖雨多次催讨未果，委托本所代理主张借款本金、约定利息及逾期利息。"
        ),
    },
]


async def _get_lawyer(db) -> User:
    """获取立案律师（古月方源），不存在则报错退出。"""
    lawyer = await db.scalar(select(User).where(User.username == LAWYER_USERNAME))
    if lawyer is None or lawyer.role != "lawyer":
        raise RuntimeError(f"律师账号 {LAWYER_USERNAME} 不存在或角色不正确")
    return lawyer


async def _get_client(db, name: str) -> ClientProfile | None:
    """按姓名精确查找客户档案。"""
    return await db.scalar(select(ClientProfile).where(ClientProfile.name == name))


async def submit_cases() -> int:
    """为四个目标客户提交立案（幂等：同名案件已存在则跳过）。"""
    created = 0
    async with SessionLocal() as db:
        lawyer = await _get_lawyer(db)
        print(f"立案律师：{lawyer.real_name}（{lawyer.username}）\n")

        for item in CASES:
            name = item["client_name"]
            client = await _get_client(db, name)
            if client is None:
                print(f"  [跳过] 客户 {name!r} 不存在，请先录入客户档案")
                continue

            # 幂等：同名案件已存在则跳过
            exists = await db.scalar(select(Case).where(Case.title == item["title"]))
            if exists is not None:
                print(f"  [跳过] 案件已存在（案号 {exists.case_no}）：{item['title']}")
                continue

            payload = CaseCreate(
                client_id=client.id,
                title=item["title"],
                case_cause=item["case_cause"],
                case_type=item["case_type"],
                court=item["court"],
                opposing_party=item["opposing_party"],
                amount=item["amount"],
                description=item["description"],
            )
            case = await case_service.create_case(db, payload, lawyer)
            created += 1
            print(
                f"  [立案] 案号 {case.case_no}｜{case.title}\n"
                f"         客户={name}｜案由={case.case_cause}｜标的额={case.amount} 元｜状态={case.status}"
            )

        print(f"\n完成：新立案 {created} 条")
    return created


async def _list_cases() -> None:
    """查看古月方源名下现有案件。"""
    async with SessionLocal() as db:
        lawyer = await _get_lawyer(db)
        rows = (
            (
                await db.execute(
                    select(Case).where(Case.created_by == lawyer.id).order_by(Case.id)
                )
            )
            .scalars()
            .all()
        )
    print(f"古月方源名下案件（created_by={lawyer.id}）共 {len(rows)} 条：")
    for c in rows:
        print(f"  {c.case_no:<14} {c.title}｜{c.status}")


async def main() -> None:
    args = sys.argv[1:]
    try:
        if "--list" in args:
            await _list_cases()
        else:
            await submit_cases()
    finally:
        await dispose_engine()


if __name__ == "__main__":
    asyncio.run(main())

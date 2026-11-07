"""生成随机测试数据：7 个随机客户账号 + 古月方源律师名下的一批客户档案。

对应开发阶段的数据填充需求。脚本幂等：账号/客户已存在则跳过，避免重复插入。

功能：
1. 创建 7 个随机「客户」角色账号（含指定的 bainingbing 与「张三」，
   其中张三的登录账号为库中已有的手机号 13900001111），
   登录账号使用真实感手机号，姓名/邮箱随机取自内置数据池。
2. 为律师「古月方源」（guyuefangyuan）创建一批客户档案，姓名、手机号、
   身份证号、地址、来源、分级、状态均随机，且全部为相对真实的模拟数据
   （禁止 111/aaa 这类占位数据）。

用法：
    cd backend
    uv run python scripts/seed_random_data.py            # 生成数据（幂等）
    uv run python scripts/seed_random_data.py --list     # 只查看现状，不写入
    uv run python scripts/seed_random_data.py --users N  # 指定随机账号数量（默认 7）
    uv run python scripts/seed_random_data.py --clients N # 指定客户数量（默认 20）
"""

import asyncio
import random
import string
import sys
from pathlib import Path

# 保证能 import 到 app 包
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import func, select

from app.core.security import hash_password
from app.database import SessionLocal, dispose_engine
from app.models.client import ClientProfile
from app.models.user import User

# ---------------------------------------------------------------------------
# 真实感数据池：所有字段均来自可读的中文姓名/地址/来源，避免占位符
# ---------------------------------------------------------------------------

# 常见中文姓氏 + 名字（用于拼出真实感姓名）
SURNAMES = [
    "王", "李", "张", "刘", "陈", "杨", "黄", "赵", "吴", "周",
    "徐", "孙", "马", "朱", "胡", "郭", "何", "高", "林", "罗",
    "郑", "梁", "谢", "宋", "唐", "许", "韩", "冯", "邓", "曹",
    "彭", "曾", "肖", "田", "董", "潘", "袁", "蔡", "蒋", "余",
    "于", "杜", "叶", "程", "苏", "魏", "吕", "丁", "任", "沈",
]

GIVEN_NAMES_MALE = [
    "建国", "志强", "伟", "磊", "军", "勇", "涛", "斌", "鹏", "杰",
    "浩", "鑫", "俊", "明", "宇", "子轩", "浩然", "铭", "泽", "瑞",
    "文轩", "博文", "天佑", "嘉豪", "一诺", "晨曦", "宇轩", "俊杰", "昊然",
]

GIVEN_NAMES_FEMALE = [
    "秀英", "丽", "敏", "静", "雪", "艳", "芳", "娜", "慧", "婷",
    "晓", "雨", "欣怡", "梦琪", "思涵", "语嫣", "婉婷", "紫萱", "若曦", "诗涵",
    "雨桐", "可欣", "梓涵", "晓梅", "雅静", "嘉怡", "乐瑶", "静怡",
]

# 城市/城区 + 街道后缀，拼成真实感地址
CITIES = [
    "北京市朝阳区", "上海市浦东新区", "广州市天河区", "深圳市南山区",
    "杭州市西湖区", "成都市武侯区", "南京市鼓楼区", "武汉市江汉区",
    "西安市雁塔区", "重庆市渝中区", "苏州市工业园区", "天津市和平区",
    "长沙市岳麓区", "青岛市市南区", "厦门市思明区", "宁波市鄞州区",
    "合肥市蜀山区", "佛山市禅城区", "东莞市南城区", "郑州市金水区",
]

STREETS = [
    "中山路", "人民路", "解放路", "建设路", "和平路", "文化路", "科技路",
    "春熙路", "南京东路", "王府井大街", "五一路", "滨海大道", "世纪大道",
    "望江路", "湖滨路", "光明路", "朝阳路", "振兴路", "学府路", "青年路",
]

COMMUNITIES = [
    "阳光花园", "翠湖天地", "锦绣江南", "万科城", "绿地中央广场", "碧桂园",
    "恒大名都", "龙湖春江天玺", "融创壹号院", "金地香山", "保利天悦",
    "中海国际社区", "华润橡树湾", "招商花园城", "首开熙悦", "远洋万和城",
]

# 身份证号地区码 + 校验位生成
ID_PREFIX = [
    "110101", "310101", "440101", "440301", "330106", "510107",
    "320102", "420103", "610113", "500103", "320505", "120101",
    "430104", "370202", "350203", "330212", "340104", "440604",
    "441900", "410105",
]

# 来源渠道
SOURCE_CHANNELS = ["转介绍", "网络咨询", "门店到访", "电话咨询", "朋友推荐", "广告投放"]

# 客户分级
CLIENT_LEVELS = ["vip", "normal"]

# 客户状态（潜在为主，少量成交/流失）
CLIENT_STATUSES = ["potential", "potential", "potential", "deal", "lost"]

# 跟进内容模板（真实感，含业务措辞）
FOLLOW_METHODS = ["phone", "wechat", "visit", "email"]

# 客户类型
CLIENT_TYPES = ["personal", "company"]

# 邮箱域名（避免 aaa@example 这类占位）
EMAIL_DOMAINS = ["163.com", "qq.com", "126.com", "sina.com", "gmail.com", "outlook.com"]


def random_phone() -> str:
    """生成真实感手机号：常见号段（13x/15x/17x/18x + 19x 常见段），避免连号占位。"""
    # 常见移动/联通/电信号段，避开 194(物联网)、179 等少见段
    prefix = random.choice(
        [
            "130", "131", "132", "133", "134", "135", "136", "137", "138", "139",
            "150", "151", "152", "153", "155", "156", "157", "158", "159",
            "170", "171", "173", "175", "176", "177", "178",
            "180", "181", "182", "183", "184", "185", "186", "187", "188", "189",
            "191", "198", "199",
        ]
    )
    tail = "".join(str(random.randint(0, 9)) for _ in range(8))
    return prefix + tail


def random_name(gender: str | None = None) -> tuple[str, str]:
    """随机姓名，返回 (姓名, 性别)。"""
    if gender is None:
        gender = random.choice(["男", "女"])
    surname = random.choice(SURNAMES)
    pool = GIVEN_NAMES_MALE if gender == "男" else GIVEN_NAMES_FEMALE
    return surname + random.choice(pool), gender


def random_id_no(gender: str | None = None) -> str:
    """生成合法格式的 18 位身份证号（含校验位），顺序码与性别一致。

    顺序码（第 17 位）奇数为男性、偶数为女性，与 GB 11643 规范一致。
    """
    prefix = random.choice(ID_PREFIX)
    year = random.randint(1960, 2002)
    month = random.randint(1, 12)
    day = random.randint(1, 28)
    # 顺序码末位：奇男偶女
    if gender == "男":
        seq_last = random.choice([1, 3, 5, 7, 9])
    elif gender == "女":
        seq_last = random.choice([0, 2, 4, 6, 8])
    else:
        seq_last = random.randint(0, 9)
    seq = f"{random.randint(0, 9)}{random.randint(0, 9)}{seq_last}"
    body = f"{prefix}{year:04d}{month:02d}{day:02d}{seq}"
    # 计算校验位（GB 11643-1999）
    weights = [7, 9, 10, 5, 8, 4, 2, 1, 6, 3, 7, 9, 10, 5, 8, 4, 2]
    codes = "10X98765432"
    total = sum(int(body[i]) * weights[i] for i in range(17))
    return body + codes[total % 11]


def random_address() -> str:
    """真实感地址：城市 + 街道 + 门牌 + 小区。"""
    city = random.choice(CITIES)
    street = random.choice(STREETS)
    community = random.choice(COMMUNITIES)
    block = random.randint(1, 30)
    unit = random.randint(1, 3)
    room = random.randint(101, 2804)
    return f"{city}{street}{random.randint(1, 200)}号{community}{block}栋{unit}单元{room}室"


def random_email(name: str) -> str:
    """根据姓名生成真实感邮箱。"""
    # 取姓名拼音首字母 + 随机数字，避免 aaa 这类占位
    prefix = "".join(random.choice(string.ascii_lowercase) for _ in range(2))
    suffix = "".join(random.choice(string.ascii_lowercase) for _ in range(4))
    return f"{prefix}{suffix}{random.randint(100, 9999)}@{random.choice(EMAIL_DOMAINS)}"


# 企业品牌词 / 行业词 / 公司性质，拼出真实感机构名
COMPANY_BRANDS = [
    "恒达", "中远", "金鼎", "华信", "瑞丰", "天成", "宏远", "盛达",
    "嘉禾", "泰和", "立信", "广源", "鼎盛", "鑫隆", "鸿图", "卓诚",
    "安泰", "博达", "正通", "荣昌",
]
COMPANY_INDUSTRIES = [
    "建筑工程", "房地产开发", "装饰装潢", "贸易", "物流运输", "餐饮管理",
    "文化传媒", "信息科技", "汽车销售", "医疗器械", "教育咨询", "建材",
    "环保科技", "机械制造", "电子商务", "企业管理",
]
COMPANY_FORMS = ["有限公司", "集团有限公司", "股份有限公司"]


def random_company_name() -> str:
    """生成真实感企业名：品牌 + 行业 + 公司性质。"""
    brand = random.choice(COMPANY_BRANDS)
    industry = random.choice(COMPANY_INDUSTRIES)
    form = random.choice(COMPANY_FORMS)
    return f"{brand}{industry}{form}"


# ---------------------------------------------------------------------------
# 指定的两个账号（含在 7 个随机账号内）
# 「zhangsan」对应用户口语里的张三，实际登录账号是手机号 13900001111（见库中现状），
# 这里按现有账号处理，不新建、不重复。
# ---------------------------------------------------------------------------
FIXED_USERS = [
    {"username": "bainingbing", "real_name": "白凝冰", "phone": "13900003001", "role": "client"},
    {"username": "13900001111", "real_name": "张三", "phone": "13900001111", "role": "client"},
]

# 默认随机账号数量（含 2 个指定账号，故随机生成 5 个）
DEFAULT_USER_COUNT = 7
DEFAULT_CLIENT_COUNT = 20

# 客户归属律师账号
LAWYER_USERNAME = "guyuefangyuan"
LAWYER_REAL_NAME = "古月方源"


def _username_from_phone(phone: str) -> str:
    return phone


async def _ensure_fixed_users(db, count: int) -> list[dict]:
    """确保客户角色账号总数为 count 个（含固定账号，幂等）。

    先落固定账号（bainingbing、张三），再统计库中已有客户角色账号总数，
    只补齐差额，多次运行不会累积超出 count 个。
    """
    created = []

    # 固定账号优先
    for item in FIXED_USERS:
        user = await db.scalar(select(User).where(User.username == item["username"]))
        if user is None:
            user = User(
                username=item["username"],
                password_hash=hash_password("client123456"),
                real_name=item["real_name"],
                role="client",
                phone=item["phone"],
                email=random_email(item["real_name"]),
                status=1,
            )
            db.add(user)
            await db.commit()
            await db.refresh(user)
            print(f"  [用户] 创建固定客户账号 {item['username']}（{item['real_name']}）")
        else:
            print(f"  [用户] 已存在，跳过 {item['username']}（{item['real_name']}）")
        created.append({"id": user.id, "username": item["username"], "real_name": item["real_name"]})

    # 统计当前客户角色账号总数，只补齐差额
    existing_client_count = await db.scalar(
        select(func.count()).select_from(User).where(User.role == "client")
    )
    existing_client_count = existing_client_count or 0
    need = count - existing_client_count

    if need <= 0:
        print(
            f"  [用户] 客户账号已有 {existing_client_count} 个，已达目标 {count} 个，无需补齐"
        )
        return created

    # 已占用的手机号与姓名（含固定账号）
    used_phones = {item["phone"] for item in FIXED_USERS}
    used_names = {item["real_name"] for item in FIXED_USERS}
    # 收集库中已有客户账号的手机号，避免撞号
    existing_phones = (
        await db.execute(select(User.phone).where(User.role == "client"))
    ).scalars().all()
    used_phones.update(p for p in existing_phones if p)

    for _ in range(need):
        # 生成唯一手机号与姓名
        while True:
            phone = random_phone()
            if phone not in used_phones:
                break
        while True:
            name, _ = random_name()
            if name not in used_names:
                break
        used_phones.add(phone)
        used_names.add(name)

        # 账号以手机号作为用户名，保持唯一
        existing = await db.scalar(select(User).where(User.username == phone))
        if existing is not None:
            print(f"  [用户] 手机号 {phone} 已存在，跳过")
            continue

        user = User(
            username=phone,
            password_hash=hash_password("client123456"),
            real_name=name,
            role="client",
            phone=phone,
            email=random_email(name),
            status=1,
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
        print(f"  [用户] 创建随机客户账号 {phone}（{name}）")
        created.append({"id": user.id, "username": phone, "real_name": name})

    return created


async def _ensure_lawyer(db) -> User:
    """确保古月方源律师账号存在（不存在则创建，供客户归属）。"""
    lawyer = await db.scalar(select(User).where(User.username == LAWYER_USERNAME))
    if lawyer is None:
        lawyer = User(
            username=LAWYER_USERNAME,
            password_hash=hash_password("gyfy3951"),
            real_name=LAWYER_REAL_NAME,
            role="lawyer",
            phone="13900003002",
            email="guyuefangyuan@example.com",
            status=1,
        )
        db.add(lawyer)
        await db.commit()
        await db.refresh(lawyer)
        print(f"  [律师] 创建律师账号 {LAWYER_USERNAME}（{LAWYER_REAL_NAME}）")
    else:
        print(f"  [律师] 已存在 {LAWYER_USERNAME}（{LAWYER_REAL_NAME}）")
    return lawyer


async def _seed_clients(db, lawyer: User, count: int) -> int:
    """为律师补齐客户档案至 count 条（幂等），数据全部随机真实感。

    只补齐差额：统计该律师名下现有客户数，不足 count 才继续新增，
    多次运行不会累积超出 count 条。
    """
    # 统计该律师名下现有客户数
    existing_count = await db.scalar(
        select(func.count())
        .select_from(ClientProfile)
        .where(ClientProfile.lawyer_id == lawyer.id)
    )
    existing_count = existing_count or 0
    need = count - existing_count

    if need <= 0:
        print(
            f"  [客户] {lawyer.real_name} 名下已有 {existing_count} 条客户档案，"
            f"已达目标 {count} 条，无需补齐"
        )
        return 0

    created = 0
    used_names: set[str] = set()
    used_phones: set[str] = set()
    used_idnos: set[str] = set()

    # 收集已有客户的姓名/手机号/身份证号，避免撞车
    existing = (
        await db.execute(
            select(ClientProfile.name, ClientProfile.phone, ClientProfile.id_no).where(
                ClientProfile.lawyer_id == lawyer.id
            )
        )
    ).all()
    for name, phone, id_no in existing:
        used_names.add(name)
        if phone:
            used_phones.add(phone)
        if id_no:
            used_idnos.add(id_no)

    for _ in range(need):
        # 先确定客户类型，再按类型生成姓名/身份证
        client_type = random.choice(CLIENT_TYPES)

        # 生成唯一姓名（个人客户需要性别，机构客户用企业名）
        while True:
            name, gender = random_name()
            if name not in used_names:
                break

        # 生成唯一手机号
        while True:
            phone = random_phone()
            if phone not in used_phones:
                break

        # 生成唯一身份证号（个人客户，且性别与证件号一致；机构客户无证件号）
        if client_type == "personal":
            while True:
                id_no = random_id_no(gender)
                if id_no not in used_idnos:
                    break
            used_idnos.add(id_no)
        else:
            id_no = None

        used_names.add(name)
        used_phones.add(phone)

        # 机构客户用真实感企业名，个人客户用姓名
        if client_type == "company":
            display_name = random_company_name()
            gender = None
        else:
            display_name = name

        client = ClientProfile(
            name=display_name,
            client_type=client_type,
            id_no=id_no,
            gender=gender,
            phone=phone,
            address=random_address(),
            source_channel=random.choice(SOURCE_CHANNELS),
            level=random.choice(CLIENT_LEVELS),
            status=random.choice(CLIENT_STATUSES),
            lawyer_id=lawyer.id,
            remark=None,
        )
        db.add(client)
        await db.commit()
        created += 1
        print(f"  [客户] {display_name}（{client_type} / {client.status} / {client.level}）→ {lawyer.real_name}")

    return created


async def _list_status() -> None:
    """打印当前用户与客户概况。"""
    async with SessionLocal() as db:
        users = (await db.execute(select(User).order_by(User.id))).scalars().all()
        clients = (await db.execute(select(ClientProfile).order_by(ClientProfile.id))).scalars().all()

    print(f"共 {len(users)} 个账号，{len(clients)} 条客户档案")
    print("\n客户角色账号：")
    for u in users:
        if u.role == "client":
            print(f"  {u.username:<14} {u.real_name:<10} {u.phone or '-'}")
    print("\n客户档案（按负责律师）：")
    lawyer_map = {u.id: u.real_name for u in users}
    for c in clients:
        owner = lawyer_map.get(c.lawyer_id, "-")
        print(f"  {c.name:<16} {c.phone or '-':<13} → {owner}")


async def main() -> None:
    args = sys.argv[1:]
    try:
        if "--list" in args:
            await _list_status()
            return

        user_count = DEFAULT_USER_COUNT
        client_count = DEFAULT_CLIENT_COUNT
        if "--users" in args:
            user_count = int(args[args.index("--users") + 1])
        if "--clients" in args:
            client_count = int(args[args.index("--clients") + 1])

        async with SessionLocal() as db:
            print(f"==> 准备创建 {user_count} 个客户账号（含 bainingbing、zhangsan）")
            await _ensure_fixed_users(db, user_count)

            print(f"\n==> 准备为律师「古月方源」创建 {client_count} 条客户档案")
            lawyer = await _ensure_lawyer(db)
            created = await _seed_clients(db, lawyer, client_count)
            print(f"\n完成：新增 {created} 条客户档案")
    finally:
        await dispose_engine()


if __name__ == "__main__":
    asyncio.run(main())

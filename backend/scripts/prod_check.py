"""上线前自检：把「部署时最容易忘、忘了就出事」的项逐条过一遍。

设计原则：

- **只读**。不改任何配置、不写数据库、不调用大模型（省钱）；
- 默认连数据库做弱口令检查，``--skip-db`` 可跳过；
- 默认不探测 Qdrant/向量服务，``--probe-ai`` 才发请求；
- 有 FAIL 时退出码为 1，可直接串进发布脚本做卡点。

用法::

    cd backend
    .venv/Scripts/python.exe scripts/prod_check.py                       # 检查本地 .env
    .venv/Scripts/python.exe scripts/prod_check.py --env-file /opt/law-firm-cms/backend/.env
    .venv/Scripts/python.exe scripts/prod_check.py --probe-ai            # 额外探测向量服务
"""

from __future__ import annotations

import argparse
import asyncio
import os
import re
import sys
from datetime import datetime
from pathlib import Path

import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import Settings
from app.core.security import verify_password

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_ENV = Path(__file__).resolve().parents[1] / ".env"
# 构建产物不入库（见 deploy/DEPLOY.md 10.6）：
# 本地开发时在仓库内 frontend/dist，服务器上由 release-frontend.sh 推到 nginx 目录。
LOCAL_DIST = ROOT / "frontend" / "dist"
PROD_DIST = Path("/var/www/law-firm/dist")
DEFAULT_DIST = LOCAL_DIST
SCHEMA_SQL = ROOT / "db" / "schema.sql"


def resolve_dist(explicit: Path | None) -> Path:
    """确定 dist 目录：命令行 > 仓库内 > nginx 目录。"""
    if explicit is not None:
        return explicit
    if (LOCAL_DIST / "index.html").is_file():
        return LOCAL_DIST
    if (PROD_DIST / "index.html").is_file():
        return PROD_DIST
    return LOCAL_DIST


# 常见弱口令：管理员账号命中任意一个都算不合规
WEAK_PASSWORDS = [
    "admin",
    "admin123",
    "123456",
    "12345678",
    "111111",
    "abc123",
    "password",
    "qwerty",
    "bnb123456",
    "gyfy3951",
]

MIN_SECRET_LEN = 32
MIN_PASSWORD_LEN = 12

_fails: list[str] = []
_warns: list[str] = []
_oks: list[str] = []


def ok(name: str, detail: str = "") -> None:
    _oks.append(name)
    print(f"  [OK  ] {name}{(' — ' + detail) if detail else ''}")


def warn(name: str, detail: str = "") -> None:
    _warns.append(name)
    print(f"  [WARN] {name}{(' — ' + detail) if detail else ''}")


def fail(name: str, detail: str = "") -> None:
    _fails.append(name)
    print(f"  [FAIL] {name}{(' — ' + detail) if detail else ''}")


def section(title: str) -> None:
    print(f"\n== {title} ==")


def parse_env(path: Path) -> dict[str, str]:
    """解析 .env 文本（只取 KEY=VALUE，忽略注释与空行）。

    ``Settings`` 会忽略 SEED_* 这类非配置项，这里单独解析一遍用来校验。
    """
    data: dict[str, str] = {}
    if not path.is_file():
        return data
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        data[key.strip()] = value.strip().strip('"').strip("'")
    return data


def check_change_me(raw: dict[str, str]) -> None:
    """模板里的 CHANGE_ME 一个都不能剩。"""
    leftovers = [k for k, v in raw.items() if "CHANGE_ME" in v.upper()]
    if leftovers:
        fail("配置模板占位值未替换", "、".join(leftovers))
    else:
        ok("无 CHANGE_ME 残留")


def check_app(s: Settings) -> None:
    section("应用与安全")
    if s.app_env == "prod":
        ok("APP_ENV", "prod（接口文档已关闭）")
    else:
        fail("APP_ENV 不是 prod", f"当前 {s.app_env}，会暴露 /docs 与 openapi.json")

    if s.debug:
        warn("DEBUG=true", "生产建议 false")
    else:
        ok("DEBUG", "false")

    secret = s.jwt_secret
    if secret == "please-generate-your-own-secret":
        fail("JWT_SECRET 仍是代码默认值")
    elif len(secret) < MIN_SECRET_LEN:
        fail("JWT_SECRET 过短", f"{len(secret)} 位，建议 >= {MIN_SECRET_LEN}")
    else:
        ok("JWT_SECRET", f"{len(secret)} 位")

    exp = s.access_token_expire_minutes
    if exp > 60 * 24 * 7:
        warn("令牌有效期过长", f"{exp} 分钟")
    else:
        ok("令牌有效期", f"{exp} 分钟")


def check_cors(s: Settings) -> None:
    section("跨域")
    origins = s.cors_origin_list
    if not origins:
        fail("CORS_ORIGINS 为空", "前后端同域也建议填写")
        return
    bad = [o for o in origins if "localhost" in o or "127.0.0.1" in o]
    if bad:
        fail("CORS 仍含本机地址", "、".join(bad))
    insecure = [o for o in origins if o.startswith("http://")]
    if insecure:
        warn("CORS 含 http:// 源", "、".join(insecure))
    if not bad:
        ok("CORS_ORIGINS", "、".join(origins))


def check_db_url(s: Settings) -> None:
    section("数据库连接")
    m = re.match(
        r"(?P<driver>[\w+]+)://(?P<user>[^:]+):(?P<pwd>[^@]*)@(?P<host>[^:/]+):(?P<port>\d+)/(?P<name>[^?]+)(?P<args>\?.*)?",
        s.database_url,
    )
    if not m:
        fail("DATABASE_URL 无法解析", "格式应为 mysql+aiomysql://user:pwd@host:port/db")
        return

    user, pwd, host, name, args = (
        m.group("user"),
        m.group("pwd"),
        m.group("host"),
        m.group("name"),
        m.group("args") or "",
    )
    if user == "root":
        fail("数据库使用 root 账号", "应建专用账号，只授 DML 权限")
    else:
        ok("数据库账号", user)

    if len(pwd) < MIN_PASSWORD_LEN:
        fail("数据库密码过短", f"{len(pwd)} 位，建议 >= {MIN_PASSWORD_LEN}")
    else:
        ok("数据库密码长度", f"{len(pwd)} 位")

    if "charset=utf8mb4" not in args:
        warn("连接串未指定 charset=utf8mb4", "中文与 emoji 可能乱码")
    else:
        ok("字符集", "utf8mb4")

    if host in ("127.0.0.1", "localhost"):
        ok("数据库位置", f"{host}（同机部署）")
    else:
        warn("数据库不在本机", f"{host}，请确认网络与防火墙")

    if name != "law_firm":
        warn("数据库名不是 law_firm", name)


def check_business(s: Settings) -> None:
    section("业务配置")
    firm = s.firm_name.strip()
    if firm in ("", "示例律师事务所") or "CHANGE_ME" in firm.upper():
        fail("FIRM_NAME 仍是占位值", f"当前「{firm}」，会写进 AI 提示词")
    else:
        ok("FIRM_NAME", firm)

    if not s.llm_api_key.strip():
        fail("LLM_API_KEY 为空", "AI 模块会整体降级为 503")
    elif "CHANGE_ME" in s.llm_api_key.upper():
        fail("LLM_API_KEY 未替换")
    else:
        ok("LLM_API_KEY", "已配置")

    if not s.llm_base_url.startswith("https://"):
        warn("LLM_BASE_URL 非 https", s.llm_base_url)

    # 向量化：云端 provider 必须有 Key，否则 RAG 问答/文书检索整体不可用；
    # tei provider 只在内存 ≥4GB 时才建议使用（bge-large 权重就 1.3GB）
    if s.embedding_provider == "tei":
        warn(
            "EMBEDDING_PROVIDER=tei",
            "自建 TEI 需额外 300MB~1.8GB 内存，2C2G 机器请改回 openai",
        )
    elif not s.embedding_key:
        fail("EMBEDDING_API_KEY 与 LLM_API_KEY 都为空", "RAG 检索不可用")
    elif "CHANGE_ME" in s.embedding_key.upper():
        where = (
            "EMBEDDING_API_KEY"
            if s.embedding_api_key.strip()
            else "EMBEDDING_API_KEY 留空时会复用 LLM_API_KEY，而它仍是占位值"
        )
        fail("向量化 Key 未替换", where)
    else:
        source = "复用 LLM_API_KEY" if not s.embedding_api_key.strip() else "独立 Key"
        ok("EMBEDDING_API_KEY", source)

    if s.embedding_provider == "openai" and not s.embedding_base_url.rstrip(
        "/"
    ).endswith("/v1"):
        warn(
            "EMBEDDING_BASE_URL 未以 /v1 结尾",
            "代码会在其后拼 /embeddings，OpenAI 兼容接口通常需要 /v1",
        )

    proxy = s.outbound_proxy.strip()
    env_proxy = [
        k
        for k in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy")
        if os.getenv(k)
    ]
    if not proxy and env_proxy:
        warn(
            "环境里有代理变量但 OUTBOUND_PROXY 为空",
            "代码会忽略它们，出站仍是直连；需要代理请写进 .env",
        )
    elif proxy:
        ok("出站代理", "已配置")
    else:
        ok("出站网络", "直连")


def check_upload(s: Settings) -> None:
    section("文件存储")
    path = Path(s.upload_dir)
    if not path.is_absolute():
        fail("UPLOAD_DIR 不是绝对路径", str(path))
    elif not path.exists():
        warn("UPLOAD_DIR 不存在", "应用启动会自动创建，确认运行用户有写权限")
    elif not os.access(path, os.W_OK):
        fail("UPLOAD_DIR 不可写", str(path))
    else:
        ok("UPLOAD_DIR", str(path))

    if str(s.rag_dir) == str(path):
        fail("rag_dir 与 upload_dir 重叠")


def check_seed_passwords(raw: dict[str, str]) -> None:
    section("种子账号密码")
    names = ["SEED_ADMIN_PASSWORD", "SEED_LAWYER_PASSWORD", "SEED_CLIENT_PASSWORD"]
    missing = [n for n in names if not raw.get(n)]
    if missing:
        fail(
            "未配置种子账号密码", "、".join(missing) + "（create_users.py 会拒绝执行）"
        )
        return
    weak = [
        n
        for n in names
        if len(raw.get(n, "")) < MIN_PASSWORD_LEN or "CHANGE_ME" in raw[n].upper()
    ]
    if weak:
        fail("种子账号密码过弱或未替换", "、".join(weak))
    else:
        ok("种子账号密码", "均已设置且长度合规")


def check_timezone() -> None:
    section("时区")
    tz_env = os.getenv("TZ", "")
    if tz_env.startswith(("Asia/Shanghai", "Asia/Chongqing")):
        ok("TZ", tz_env)
        return
    zone_file = Path("/etc/timezone")
    if zone_file.is_file():
        value = zone_file.read_text(encoding="utf-8", errors="ignore").strip()
        if value in ("Asia/Shanghai", "Asia/Chongqing", "PRC"):
            ok("系统时区", value)
            return
        fail("系统时区不是东八区", f"{value}；date.today() 会整体偏移")
        return
    # Windows / 未暴露 /etc/timezone：用当前偏移判断
    offset = datetime.now().astimezone().utcoffset()
    hours = offset.total_seconds() / 3600 if offset else 0
    if abs(hours - 8) < 0.01:
        ok("系统时区", "UTC+8")
    else:
        fail("系统时区偏移不是 +8", f"当前 UTC{hours:+g}")


def check_python() -> None:
    section("运行时")
    ver = sys.version_info
    if ver >= (3, 13):
        ok("Python", f"{ver.major}.{ver.minor}.{ver.micro}")
    else:
        fail("Python 版本过低", f"{ver.major}.{ver.minor}，项目要求 >= 3.13")


def check_host(s: Settings) -> None:
    """内存与 swap：2C2G 机器上唯一会「突然全站 502」的原因就是 OOM。

    参考占用：MySQL 250~450MB + Qdrant 150~250MB + uvicorn 200~300MB +
    nginx 20MB + 系统 200MB ≈ 0.9~1.2GB；PDF 解析峰值再加 200~400MB。
    自建 TEI（bge-large）要再吃 1.4~1.8GB，2C2G 必然被 OOM killer 杀掉。
    """
    section("主机资源")
    meminfo = Path("/proc/meminfo")
    if not meminfo.is_file():
        ok("主机内存", "非 Linux，跳过")
        return
    values: dict[str, int] = {}
    for line in meminfo.read_text(encoding="utf-8", errors="ignore").splitlines():
        key, _, rest = line.partition(":")
        if rest.strip().endswith("kB"):
            values[key] = int(rest.split()[0])
    total_mb = values.get("MemTotal", 0) // 1024
    swap_mb = values.get("SwapTotal", 0) // 1024

    # 标称 2GiB 的机型（阿里云/腾讯云 2C2G）经内核与硬件保留后，
    # /proc/meminfo 的 MemTotal 实测常为 1.6~1.9GB，按 1800MB 卡会把合格机器误判。
    # 判定依据改为「物理内存 + swap 能否扛住峰值」：1400MB 以上且有 >=1GB swap
    # 即为可用；低于 1400MB 或没有 swap 兜底才判失败。
    if total_mb < 1400:
        fail("内存过小", f"{total_mb}MB；最低 2GB，建议 4GB")
    elif total_mb < 1800 and swap_mb < 1024:
        fail("内存不足且无 swap", f"{total_mb}MB 物理内存 + {swap_mb}MB swap，峰值必 OOM")
    elif total_mb < 1800:
        ok("内存总量", f"{total_mb}MB（2G 机型内核预留后正常，由 {swap_mb}MB swap 兜底）")
    else:
        ok("内存总量", f"{total_mb}MB")

    if s.embedding_provider == "tei" and total_mb < 4000:
        fail(
            "自建 TEI 内存不足",
            f"{total_mb}MB 装不下 bge-large（1.4~1.8GB），请改 EMBEDDING_PROVIDER=openai",
        )

    if swap_mb == 0:
        warn("未启用 swap", "PDF/Excel 解析峰值可能触发 OOM，建议加 2GB swap")
    elif swap_mb < 1024:
        warn("swap 偏小", f"{swap_mb}MB，建议 2048MB")
    else:
        ok("swap", f"{swap_mb}MB")


def check_frontend(dist: Path) -> None:
    section("前端构建产物")
    index = dist / "index.html"
    if not index.is_file():
        fail(
            "dist/index.html 不存在",
            "本地执行 bash deploy/release-frontend.sh <SERVER> 上传构建产物",
        )
        return
    ok("dist/index.html", str(index))

    assets = dist / "assets"
    if not assets.is_dir():
        fail("dist/assets 不存在")
        return

    # 构建产物是否包含最新的字典接口调用（模块 11.3.1 的接线）。
    # 源码是 request.get('/dicts')，打包后为 e.get(`/dicts`)——注意是反引号，
    # 且不能用裸 /dicts 判定：/admin/dicts 里也含这个子串。
    has_dict_api = any(
        "`/dicts`" in p.read_text("utf-8", errors="ignore") for p in assets.glob("*.js")
    )
    if has_dict_api:
        ok("构建产物包含字典接口调用")
    else:
        fail("dist 可能是旧构建", "未找到 /dicts 调用，重新执行 npm run build")

    # mtime 比较只在「dist 与源码同仓库」时有意义（本地开发）。
    # 服务器上 dist 来自 release-frontend.sh 上传、源码来自 git checkout，
    # 两者时间基准不同，比较必然误报，直接跳过。
    src = ROOT / "frontend" / "src"
    if dist.resolve() != LOCAL_DIST.resolve():
        ok("dist 位于 nginx 目录", "由发布脚本上传，跳过 mtime 比对")
    elif src.is_dir():
        newest = max(
            (p.stat().st_mtime for p in src.rglob("*") if p.is_file()), default=0
        )
        if newest > index.stat().st_mtime:
            fail(
                "dist 早于源码修改时间",
                datetime.fromtimestamp(newest).strftime("%Y-%m-%d %H:%M:%S"),
            )
        else:
            ok("dist 不早于源码", "构建是最新的")


def check_schema_sql() -> None:
    section("建表脚本")
    if not SCHEMA_SQL.is_file():
        warn("未找到 db/schema.sql")
        return
    body = SCHEMA_SQL.read_text(encoding="utf-8", errors="ignore")
    drops = len(re.findall(r"DROP TABLE", body, re.IGNORECASE))
    if drops:
        warn(
            "schema.sql 含 DROP TABLE",
            f"{drops} 处；生产库严禁执行，只用 mysqldump 恢复或单独建库",
        )
    else:
        ok("schema.sql 无破坏性语句")


async def check_database(s: Settings) -> None:
    section("数据库巡检（只读）")
    engine = create_async_engine(s.database_url, pool_pre_ping=True)
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
            ok("数据库连通")

            tables = await conn.scalar(
                text(
                    "SELECT COUNT(*) FROM information_schema.tables "
                    "WHERE table_schema = DATABASE()"
                )
            )
            if tables and tables >= 20:
                ok("表数量", f"{tables} 张")
            else:
                fail("表数量异常", f"{tables} 张，预期 >= 20")

            rows = (
                await conn.execute(
                    text("SELECT id, username, role, status, password_hash FROM user")
                )
            ).all()
            admins = [r for r in rows if r.role == "admin"]
            if not admins:
                fail("没有管理员账号")
            elif len(admins) == 1:
                ok("管理员账号", f"{admins[0].username}（唯一）")
            else:
                warn("存在多个管理员", "、".join(a.username for a in admins))

            weak: list[str] = []
            for row in rows:
                hits = [
                    w for w in WEAK_PASSWORDS if verify_password(w, row.password_hash)
                ]
                if row.username in WEAK_PASSWORDS:
                    hits.append(row.username)
                if hits:
                    weak.append(f"{row.username}({row.role})")
            if weak:
                fail("存在弱口令账号", "、".join(weak) + "；上线前必须改密")
            else:
                ok("账号弱口令扫描", f"检查 {len(rows)} 个账号，未命中")
    except Exception as exc:  # noqa: BLE001  连通失败就是检查结果本身
        fail("数据库不可用", str(exc).splitlines()[0][:160])
    finally:
        await engine.dispose()


async def probe_ai(s: Settings) -> None:
    section("AI 依赖探测")
    async with httpx.AsyncClient(timeout=5.0) as client:
        try:
            r = await client.get(
                f"{s.qdrant_url.rstrip('/')}/collections/{s.qdrant_collection}"
            )
            if r.status_code == 200:
                result = r.json().get("result") or {}
                points = result.get("points_count") or 0
                vectors = ((result.get("config") or {}).get("params") or {}).get(
                    "vectors"
                ) or {}
                dim = vectors.get("size") if isinstance(vectors, dict) else None
                if points == 0:
                    # 空集合不会报错，只会让每次检索都返回「资料不足」，很难被发现
                    fail(
                        "向量库为空",
                        f"{s.qdrant_collection} 0 个点，AI 检索会全部落空；"
                        "先导入快照或跑 kb_builder --reindex",
                    )
                elif dim is not None and dim != s.embedding_dim:
                    fail(
                        "向量维度不匹配",
                        f"集合 {dim} 维，EMBEDDING_DIM={s.embedding_dim}，写入与检索都会失败",
                    )
                else:
                    ok("Qdrant", f"{s.qdrant_collection} / {points} 个点 / {dim} 维")
            else:
                fail("Qdrant 集合不可用", f"HTTP {r.status_code}")
        except Exception as exc:  # noqa: BLE001
            fail("Qdrant 连不上", str(exc).splitlines()[0][:120])

        if s.embedding_provider == "tei":
            try:
                r = await client.get(f"{s.embedding_base_url.rstrip('/')}/health")
                if r.status_code == 200:
                    ok("TEI 向量服务", "healthy")
                else:
                    fail("TEI 向量服务异常", f"HTTP {r.status_code}")
            except Exception as exc:  # noqa: BLE001
                fail("TEI 连不上", str(exc).splitlines()[0][:120])
        else:
            # 云端接口没有 /health，用一次真实调用探活：鉴权/模型/维度一并验证
            url = f"{s.embedding_base_url.rstrip('/')}/embeddings"
            payload = {"model": s.embedding_model, "input": ["健康检查"]}
            if s.embedding_dim:
                payload["dimensions"] = s.embedding_dim
            try:
                r = await client.post(
                    url,
                    json=payload,
                    headers={"Authorization": f"Bearer {s.embedding_key}"},
                    timeout=20.0,
                )
                if r.status_code != 200:
                    fail("Embedding 接口异常", f"HTTP {r.status_code}：{r.text[:160]}")
                else:
                    data = (r.json() or {}).get("data") or []
                    got = len(data[0].get("embedding") or []) if data else 0
                    if got == s.embedding_dim:
                        ok("Embedding 接口", f"{s.embedding_model} / {got} 维")
                    else:
                        fail(
                            "Embedding 维度不匹配",
                            f"模型返回 {got} 维，配置 EMBEDDING_DIM={s.embedding_dim}",
                        )
            except Exception as exc:  # noqa: BLE001
                fail("Embedding 接口连不上", str(exc).splitlines()[0][:120])


async def main() -> int:
    parser = argparse.ArgumentParser(description="上线前自检（只读）")
    parser.add_argument("--env-file", type=Path, default=DEFAULT_ENV)
    parser.add_argument(
        "--dist", type=Path, default=None, help="构建产物目录，默认自动探测"
    )
    parser.add_argument("--skip-db", action="store_true", help="跳过数据库巡检")
    parser.add_argument(
        "--probe-ai", action="store_true", help="探测 Qdrant 与向量化服务"
    )
    args = parser.parse_args()

    env_path: Path = args.env_file
    print(f"检查配置：{env_path}")
    if not env_path.is_file():
        print(f"[FAIL] 配置文件不存在：{env_path}")
        return 1

    s = Settings(_env_file=env_path)  # type: ignore[call-arg]
    raw = parse_env(env_path)

    check_app(s)
    check_cors(s)
    check_db_url(s)
    check_business(s)
    check_upload(s)
    check_change_me(raw)
    check_seed_passwords(raw)
    check_timezone()
    check_python()
    check_host(s)
    check_frontend(resolve_dist(args.dist))
    check_schema_sql()

    if not args.skip_db:
        await check_database(s)
    if args.probe_ai:
        await probe_ai(s)

    print("\n" + "=" * 60)
    print(f"通过 {len(_oks)} 项 | 警告 {len(_warns)} 项 | 失败 {len(_fails)} 项")
    if _fails:
        print("\n必须先解决：")
        for name in _fails:
            print(f"  - {name}")
        return 1
    print("自检通过，可以发布。")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

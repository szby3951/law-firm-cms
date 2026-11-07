"""法律知识库构建脚本（模块 9.1）。

一次把「法条原文 → MySQL → 向量库」打通，分三步，可单独执行：

.. code-block:: text

    uv run python scripts/kb_builder.py --check           # 看现状（条文数/向量数/服务健康）
    uv run python scripts/kb_builder.py --fetch           # 下载法条原文到 rag/law
    uv run python scripts/kb_builder.py --parse           # 解析入库（幂等，可重复跑）
    uv run python scripts/kb_builder.py --index           # 向量化写入 Qdrant
    uv run python scripts/kb_builder.py --all             # fetch + parse + index
    uv run python scripts/kb_builder.py --seed-faq        # 写入律所 FAQ 示例并向量化
    uv run python scripts/kb_builder.py --reset-vectors   # 清空向量后重建索引

数据来源
--------
法条原文取自开源镜像仓库 ``LawRefBook/Laws``（GitHub，约 1800 stars），
文件按「一部法律一个 Markdown」组织，格式规整（``# 法律名`` / ``## 第一章`` /
``第X条 正文``），便于解析。选它而不是直接爬「国家法律法规数据库」，是因为
后者接口已改为 SPA + 私有 JSON API（参数结构未公开），抓取脆弱且易触发限流。

解析规则
--------
- ``# 法律名``：文件首个一级标题，作为 ``law_name``；
- 其余一级标题（如「总则」「物权」）与 ``##`` / ``###`` 标题：作为 ``chapter``，
  按「编 → 章 → 节」拼接；
- ``第X条``：一条法条，后续段落（款）并入正文，直到下一条或下个标题。

为什么要「一条一存、向量再切块」
--------------------------------
``law_article.content`` 保留**完整原文**，因为引用法条时必须给全文；而本地
TEI 单条输入上限 512 token（中文约 1 字 ≈ 1 token），超过会被 413 拒绝，
所以向量化阶段由 :mod:`app.services.kb_service` 切成 ≤460 字的块。
两者分离，既能完整引用，又能安全向量化。
"""

from __future__ import annotations

import argparse
import asyncio
import re
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx
from sqlalchemy import select

from app.config import settings
from app.database import SessionLocal, dispose_engine
from app.models.kb_document import KbDocument
from app.models.law_article import LawArticle
from app.services import kb_service

DATA_DIR = settings.rag_dir / "law"
RAW_BASE = "https://raw.githubusercontent.com/LawRefBook/Laws/master"

# 需要入库的四部法律。民法典按编拆成 8 个文件，其余各 1 个文件（取最新版本）。
SOURCES: list[dict[str, str]] = [
    {"law": "中华人民共和国民法典", "path": "民法典/总则.md"},
    {"law": "中华人民共和国民法典", "path": "民法典/物权编.md"},
    {"law": "中华人民共和国民法典", "path": "民法典/合同编.md"},
    {"law": "中华人民共和国民法典", "path": "民法典/人格权编.md"},
    {"law": "中华人民共和国民法典", "path": "民法典/婚姻家庭编.md"},
    {"law": "中华人民共和国民法典", "path": "民法典/继承编.md"},
    {"law": "中华人民共和国民法典", "path": "民法典/侵权责任编.md"},
    {"law": "中华人民共和国民法典", "path": "民法典/附则.md"},
    {"law": "中华人民共和国刑法", "path": "刑法/刑法(2023-12-29).md"},
    {
        "law": "中华人民共和国民事诉讼法",
        "path": "诉讼与非诉讼程序法/民事诉讼法(2023-09-01).md",
    },
    {"law": "中华人民共和国公司法", "path": "民法商法/公司法(2023-12-29).md"},
]

ARTICLE_RE = re.compile(
    r"^(第[一二三四五六七八九十百千零〇两0-9０-９]{1,12}条)[\s　]*(.*)$"
)
BIAN_RE = re.compile(r"^第[一二三四五六七八九十百千零〇两0-9]+编")
ZHANG_RE = re.compile(r"^第[一二三四五六七八九十百千零〇两0-9]+章")
JIE_RE = re.compile(r"^第[一二三四五六七八九十百千零〇两0-9]+节")


@dataclass
class ParsedArticle:
    """解析出的一条法条。"""

    law_name: str
    chapter: str
    article_no: str
    content: str


# ---------------------------------------------------------------------------
# 1. 下载
# ---------------------------------------------------------------------------


def _local_path(rel_path: str) -> Path:
    return DATA_DIR / rel_path


async def fetch_sources(*, force: bool = False) -> int:
    """把法条 Markdown 下载到 ``backend/rag/law``，返回本次实际下载的文件数。"""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    downloaded = 0
    async with httpx.AsyncClient(timeout=60, follow_redirects=True) as client:
        for item in SOURCES:
            target = _local_path(item["path"])
            if target.exists() and not force:
                print(f"  跳过（已存在） {item['path']}")
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            url = f"{RAW_BASE}/{httpx.URL(item['path'])}"
            try:
                resp = await client.get(url)
                resp.raise_for_status()
            except httpx.HTTPError as exc:
                print(f"  下载失败 {item['path']}：{exc}")
                continue
            target.write_text(resp.text, encoding="utf-8")
            downloaded += 1
            print(f"  已下载 {item['path']}  ({len(resp.text) // 1024} KB)")
    return downloaded


# ---------------------------------------------------------------------------
# 2. 解析
# ---------------------------------------------------------------------------


def parse_markdown(path: Path, law_name: str) -> list[ParsedArticle]:
    """把一个法律 Markdown 解析成法条列表。"""
    lines = path.read_text(encoding="utf-8").splitlines()
    articles: list[ParsedArticle] = []
    levels = {"编": "", "章": "", "节": ""}
    seen_title = False
    current_no: str | None = None
    current_body: list[str] = []

    def chapter_text() -> str:
        parts = [levels["编"], levels["章"], levels["节"]]
        return " ".join(p for p in parts if p)[:128]

    def flush() -> None:
        nonlocal current_no, current_body
        if current_no:
            body = "\n".join(x.strip() for x in current_body if x.strip()).strip()
            if body:
                articles.append(
                    ParsedArticle(
                        law_name=law_name,
                        chapter=chapter_text(),
                        article_no=current_no,
                        content=f"{current_no} {body}".strip(),
                    )
                )
        current_no = None
        current_body = []

    for raw in lines:
        line = raw.strip()
        if not line:
            continue

        if line.startswith("#"):
            hashes = len(line) - len(line.lstrip("#"))
            title = line.lstrip("#").strip()
            flush()
            if hashes == 1:
                if not seen_title:
                    seen_title = True  # 文件首个一级标题 = 法律名
                else:
                    levels = {"编": title, "章": "", "节": ""}
                continue
            if BIAN_RE.match(title):
                levels = {"编": title, "章": "", "节": ""}
            elif ZHANG_RE.match(title):
                levels["章"] = title
                levels["节"] = ""
            elif JIE_RE.match(title):
                levels["节"] = title
            else:
                # 非「第X编/章/节」的标题（如「## 附则」）当作章
                levels["章"] = title
                levels["节"] = ""
            continue

        match = ARTICLE_RE.match(line)
        if match:
            flush()
            current_no = match.group(1)
            rest = match.group(2).strip()
            current_body = [rest] if rest else []
            continue

        if current_no:
            current_body.append(line)

    flush()
    return articles


def _sort_key(article_no: str) -> tuple[int, str]:
    """按条号数字排序，避免「第十条」排在「第二条」前面。"""

    def cn2int(text: str) -> int:
        digits = {
            "零": 0,
            "〇": 0,
            "一": 1,
            "二": 2,
            "两": 2,
            "三": 3,
            "四": 4,
            "五": 5,
            "六": 6,
            "七": 7,
            "八": 8,
            "九": 9,
        }
        units = {"十": 10, "百": 100, "千": 1000}
        body = text.removeprefix("第").removesuffix("条")
        if body.isdigit():
            return int(body)
        total = 0
        current = 0
        for ch in body:
            if ch in digits:
                current = digits[ch]
            elif ch in units:
                total += (current or 1) * units[ch]
                current = 0
        return total + current

    try:
        return (cn2int(article_no), article_no)
    except Exception:  # noqa: BLE001 - 无法解析时退回字符串序
        return (10**9, article_no)


async def parse_and_store(*, only_missing: bool = False) -> dict[str, int]:
    """解析全部源文件并写入 ``law_article``（幂等）。"""
    parsed: list[ParsedArticle] = []
    for item in SOURCES:
        target = _local_path(item["path"])
        if not target.exists():
            print(f"  缺少文件，跳过：{item['path']}（先执行 --fetch）")
            continue
        rows = parse_markdown(target, item["law"])
        print(f"  解析 {item['path']:<45} {len(rows):>5} 条")
        parsed.extend(rows)

    if not parsed:
        print("没有解析到任何条文，请先执行 --fetch")
        return {"inserted": 0, "updated": 0, "skipped": 0}

    # 同一 (法律, 条号) 只保留最长的一条正文，防止多文件重叠导致重复
    dedup: dict[tuple[str, str], ParsedArticle] = {}
    for row in parsed:
        key = (row.law_name, row.article_no)
        old = dedup.get(key)
        if old is None or len(row.content) > len(old.content):
            dedup[key] = row
    rows = sorted(dedup.values(), key=lambda r: (r.law_name, _sort_key(r.article_no)))

    inserted = updated = skipped = 0
    async with SessionLocal() as session:
        existing_rows = await session.execute(
            select(LawArticle.law_name, LawArticle.article_no)
        )
        existing = {(n, a) for n, a in existing_rows.all()}
        null_vector_rows = await session.execute(
            select(LawArticle.id, LawArticle.law_name, LawArticle.article_no).where(
                LawArticle.vector_id.is_(None)
            )
        )
        need_vector = {(n, a) for _, n, a in null_vector_rows.all()}

        for row in rows:
            key = (row.law_name, row.article_no)
            if key in existing:
                if only_missing:
                    skipped += 1
                    continue
                art = await session.scalar(
                    select(LawArticle).where(
                        LawArticle.law_name == row.law_name,
                        LawArticle.article_no == row.article_no,
                    )
                )
                if art and art.content != row.content:
                    art.content = row.content
                    art.chapter = row.chapter
                    if key not in need_vector:
                        art.vector_id = None  # 正文变了，向量要重算
                    updated += 1
                else:
                    skipped += 1
                continue
            session.add(
                LawArticle(
                    law_name=row.law_name,
                    chapter=row.chapter,
                    article_no=row.article_no,
                    content=row.content,
                    effective_status="有效",
                )
            )
            inserted += 1
            existing.add(key)
        await session.commit()

    return {"inserted": inserted, "updated": updated, "skipped": skipped}


# ---------------------------------------------------------------------------
# 3. 向量化
# ---------------------------------------------------------------------------


async def index_articles(*, reindex_all: bool = False) -> int:
    """把尚未向量化（或全部）的法条写入 Qdrant，顺带补齐律所知识。

    注意：查询与回写必须在**同一个会话**内完成，否则对象在会话关闭后变为
    detached，``commit`` 不会产生 UPDATE，``vector_id`` 会一直是 NULL。
    """
    total_points = 0
    async with SessionLocal() as session:
        stmt = select(LawArticle).order_by(LawArticle.id)
        if not reindex_all:
            stmt = stmt.where(LawArticle.vector_id.is_(None))
        result = await session.execute(stmt)
        articles = list(result.scalars().all())

        if not articles:
            print("  没有待向量化的法条（如已全部入库，需要重建请加 --reindex）")
        else:
            total = len(articles)
            print(f"  待向量化 {total} 条法条…")

            def progress(done: int, all_count: int) -> None:
                pct = done * 100 // max(1, all_count)
                bar = "█" * (pct // 5) + "·" * (20 - pct // 5)
                print(f"\r  [{bar}] {done}/{all_count} ({pct}%)", end="", flush=True)

            points = await kb_service.index_law_articles(
                session, articles, window=64, progress=progress
            )
            print()
            print(f"  法条：写入向量点 {points} 个（{total} 条）")
            total_points += points

    # 律所知识（FAQ/案例/手册）也走同一个 collection
    async with SessionLocal() as session:
        kb_points = await kb_service.index_pending_kb_documents(session)
    if kb_points:
        print(f"  律所知识：写入向量点 {kb_points} 个")
        total_points += kb_points

    return total_points


# ---------------------------------------------------------------------------
# 4. 律所 FAQ 示例（9.1.5）
# ---------------------------------------------------------------------------

FAQ_SEEDS: list[dict[str, str]] = [
    {
        "category": "faq",
        "title": "委托律师需要准备哪些材料？",
        "content": (
            "首次到所办理委托，请携带：1）本人身份证原件及复印件；"
            "2）与案件相关的合同、协议、转账凭证等书面材料；"
            "3）聊天记录、录音、照片等电子证据的原始载体（手机/硬盘）；"
            "4）如委托他人代办，需提供授权委托书及受托人身份证。"
            "材料不齐也可先登记咨询，由承办律师列出补充清单。"
        ),
    },
    {
        "category": "faq",
        "title": "律师费如何收取、何时开票？",
        "content": (
            "本所收费方式分三类：按标的比例（财产类案件）、按件计费（非诉与文书）、"
            "按小时计费（专项咨询）。委托合同签订后三个工作日内支付首期款，"
            "财务在款项到账后开具增值税普通发票或专用发票。"
            "风险代理仅适用于法律允许的案件类型，需在合同中单独约定。"
        ),
    },
    {
        "category": "faq",
        "title": "案件一般多久能结案？",
        "content": (
            "一审民事案件适用普通程序的，法定审限为立案之日起六个月，"
            "简易程序为三个月；刑事案件一般两个月内宣判，最迟不超过三个月。"
            "实际周期受送达、鉴定、评估、管辖异议等环节影响，"
            "承办法官会在每个节点通过「我的案件」同步进展。"
        ),
    },
    {
        "category": "faq",
        "title": "如何查询案件进度和开庭时间？",
        "content": (
            "登录当事人端后进入「我的案件」，可看到案件状态、承办律师、"
            "开庭时间与已生成的法律文书；「日程提醒」会在开庭前三天推送通知。"
            "如需口头了解，可直接在「在线留言」给承办律师留言，工作时间内一般当天回复。"
        ),
    },
    {
        "category": "faq",
        "title": "证据材料可以分次提交吗？",
        "content": (
            "可以。举证期限内分次提交不影响效力，但每次提交请附《证据清单》，"
            "载明证据名称、证明目的与页数，并保留提交回执。"
            "超过举证期限提交的证据，对方可能提出异议，由法庭决定是否采纳。"
        ),
    },
    {
        "category": "faq",
        "title": "对承办律师不满意可以更换吗？",
        "content": (
            "可以。委托合同履行期间，当事人有权提出更换承办律师，"
            "由律所主任在收到申请后三个工作日内协调，已发生的服务费用按合同约定结算。"
            "更换不影响案件材料的移交，原承办律师需在三个工作日内完成卷宗交接。"
        ),
    },
    {
        "category": "case_summary",
        "title": "示例：房屋租赁合同押金返还纠纷（要点提炼）",
        "content": (
            "【示例数据，仅供检索演示】承租方退租后，出租方以「墙面污损」为由扣留押金。"
            "争议焦点：1）墙面污损是否属于正常使用损耗；2）押金条款是否约定扣除标准；"
            "3）出租方是否在约定期限内提出异议。"
            "办案要点：调取入住时的房屋交接单与照片，比对退租时的状态；"
            "核查合同是否就清洁费、维修费单列；若出租方未在合理期限内核验，"
            "可主张全额返还并请求逾期利息。判决结果：支持返还押金及利息。"
        ),
    },
    {
        "category": "manual",
        "title": "示例：民事诉讼一审办案流程清单",
        "content": (
            "1）接案：核实当事人身份与诉讼时效，签署委托合同与授权委托书；"
            "2）立案：准备起诉状、证据清单、主体资格材料，向有管辖权的法院提交；"
            "3）送达与答辩：跟踪送达回证，评估对方答辩意见；"
            "4）举证与质证：在举证期限内提交证据，准备质证意见；"
            "5）开庭：庭前准备发问提纲与代理意见，庭后三个工作日内提交代理词；"
            "6）判后：评估上诉必要性，办理退费与归档。"
        ),
    },
]


async def seed_faq(*, index: bool = True) -> int:
    """写入律所 FAQ/案例/手册示例数据，并向量化。"""
    created = 0
    async with SessionLocal() as session:
        for item in FAQ_SEEDS:
            exists = await session.scalar(
                select(KbDocument.id).where(KbDocument.title == item["title"])
            )
            if exists:
                continue
            doc = KbDocument(
                title=item["title"],
                category=item["category"],
                content=item["content"],
            )
            session.add(doc)
            created += 1
        await session.commit()

        if index:
            result = await session.execute(
                select(KbDocument).where(KbDocument.vector_id.is_(None))
            )
            pending = list(result.scalars().all())
            for doc in pending:
                chunks = await kb_service.index_kb_document(session, doc)
                print(f"  向量化「{doc.title}」 → {chunks} 块")
    return created


# ---------------------------------------------------------------------------
# 5. 现状
# ---------------------------------------------------------------------------


async def show_check() -> None:
    """打印知识库现状。"""
    async with SessionLocal() as session:
        stats = await kb_service.kb_stats(session)
    print("\n=== 知识库现状 ===")
    print(f"  法条总数      : {stats['law_total']} 条")
    for name, count in sorted(stats["law_by_name"].items(), key=lambda x: -x[1]):
        print(f"    - {name:<18} {count:>5} 条")
    print(f"  律所知识      : {stats['firm_total']} 篇 {stats['firm_by_category']}")
    print(
        f"  向量点数      : {stats['vector_points']}（collection: {stats['collection']}）"
    )
    print(
        f"  Embedding     : {'在线' if stats['embedding_ok'] else '离线'}"
        f" {stats['embedding_model']} / {stats['embedding_dim']} 维"
        + (f" ！{stats['embedding_error']}" if stats["embedding_error"] else "")
    )
    print(
        f"  Qdrant        : {'在线' if stats['qdrant_ok'] else '离线'}"
        + (f" ！{stats['qdrant_error']}" if stats["qdrant_error"] else "")
    )
    if stats["law_total"]:
        expect = stats["law_total"]
        print(
            f"  覆盖率        : 法条 {stats['law_total']} 条 / 向量 {stats['vector_points']} 点"
            f"（超长条文会被切成多块，点数 ≥ 条数即为全覆盖）"
        )
        if stats["vector_points"] < expect:
            print("  ⚠ 向量数少于条文数，请执行 --index 补跑")


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------


async def main() -> None:
    parser = argparse.ArgumentParser(
        description="构建法律知识库（模块9.1）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--check", action="store_true", help="查看知识库现状")
    parser.add_argument("--fetch", action="store_true", help="下载法条原文到 rag/law")
    parser.add_argument("--parse", action="store_true", help="解析法条并写入 MySQL")
    parser.add_argument("--index", action="store_true", help="向量化未入库的法条")
    parser.add_argument("--reindex", action="store_true", help="强制重新向量化全部法条")
    parser.add_argument("--all", action="store_true", help="fetch + parse + index")
    parser.add_argument("--seed-faq", action="store_true", help="写入律所 FAQ 示例")
    parser.add_argument(
        "--reset-vectors", action="store_true", help="删除并重建向量集合"
    )
    parser.add_argument("--force", action="store_true", help="强制重新下载")
    args = parser.parse_args()

    if not any(
        [
            args.check,
            args.fetch,
            args.parse,
            args.index,
            args.reindex,
            args.all,
            args.seed_faq,
            args.reset_vectors,
        ]
    ):
        parser.print_help()
        return

    try:
        if args.reset_vectors:
            client = kb_service.get_client()
            try:
                if await client.collection_exists(settings.qdrant_collection):
                    await client.delete_collection(settings.qdrant_collection)
                    print(f"已删除 collection {settings.qdrant_collection}")
                await kb_service.ensure_collection(client)
            finally:
                await client.close()
            async with SessionLocal() as session:
                laws, docs = await kb_service.clear_vector_ids(session)
            print(f"已清空 vector_id：法条 {laws} 条、律所知识 {docs} 条")

        if args.fetch or args.all:
            print("=== 下载法条原文 ===")
            count = await fetch_sources(force=args.force)
            print(f"本次下载 {count} 个文件 → {DATA_DIR}")

        if args.parse or args.all:
            print("=== 解析并入库 ===")
            result = await parse_and_store()
            print(
                f"新增 {result['inserted']} 条，更新 {result['updated']} 条，"
                f"跳过 {result['skipped']} 条"
            )

        if args.index or args.all:
            print("=== 向量化 ===")
            health = await kb_service.embedding.check_health()
            if not health["ok"]:
                hint = (
                    "请先启动 embedding 容器"
                    if settings.embedding_provider == "tei"
                    else "请检查 EMBEDDING_API_KEY（或 LLM_API_KEY）与网络"
                )
                print(
                    f"向量服务不可用：{health.get('error')}\n"
                    f"{hint}（{settings.embedding_base_url}）后再执行 --index"
                )
                return
            await index_articles()

        if args.reindex:
            print("=== 重新向量化全部法条 ===")
            health = await kb_service.embedding.check_health()
            if not health["ok"]:
                print(f"向量服务不可用：{health.get('error')}")
                return
            await index_articles(reindex_all=True)

        if args.seed_faq:
            print("=== 写入律所知识示例 ===")
            health = await kb_service.embedding.check_health()
            created = await seed_faq(index=bool(health["ok"]))
            print(f"新增 {created} 篇律所知识（FAQ/案例/手册）")
            if not health["ok"]:
                print("向量服务不可用，稍后用 --index 补跑（律所知识会一并处理）")

        if args.check or args.all:
            await show_check()
    finally:
        await dispose_engine()


if __name__ == "__main__":
    asyncio.run(main())

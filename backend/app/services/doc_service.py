"""文书管理业务逻辑：模板 CRUD、文书 CRUD、模板变量填充、docx 导出。

权限约定：

- 管理员：全所文书与模板可见可改；
- 律师：可读「本人创建」或「本人承办案件」下的文书，并可在本人承办
  案件下新建/编辑；模板库为全所共享，律师与管理员均可维护；
- 客户：只能查看/下载 ``status='published'`` 且属于本人案件的文书，
  相关接口集中在 ``/api/my/documents``。
"""

import re
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

from sqlalchemy import Select, func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.exceptions import BadRequest, Forbidden, NotFound
from app.models.attachment import Attachment
from app.models.case import Case
from app.models.case_lawyer import CaseLawyer
from app.models.client import ClientProfile
from app.models.document import DocTemplate, Document
from app.models.user import User
from app.schemas.document import (
    DOC_TYPE_LABELS,
    DocumentFromTemplateIn,
    DocumentIn,
    GeneratedDocOut,
    TemplateIn,
)
from app.services.docx_export import build_docx, html_to_text

# 模板占位符：{客户姓名}、{案号} 等，限制长度避免误匹配大段花括号内容
VAR_PATTERN = re.compile(r"\{([^{}\n]{1,20})\}")
# 列表摘要长度
EXCERPT_LENGTH = 80

# 英文占位符别名 → 中文变量名，方便模板作者混用
_VAR_ALIASES = {
    "client_name": "客户姓名",
    "client_phone": "客户电话",
    "client_address": "客户地址",
    "client_id_no": "客户证件号",
    "client_gender": "客户性别",
    "case_no": "案号",
    "case_title": "案件标题",
    "case_cause": "案由",
    "court": "受理法院",
    "opposing_party": "对方当事人",
    "amount": "标的额",
    "lawyer_name": "委托律师",
    "firm_name": "律所名称",
    "firm_address": "律所地址",
    "firm_phone": "律所电话",
    "today": "今日日期",
    "year": "年份",
    "month": "月份",
    "day": "日期",
}

_CASE_STATUS_LABELS = {
    "consulting": "咨询中",
    "filed": "已立案",
    "handling": "办理中",
    "pending_close": "待结案",
    "closed": "已结案",
    "withdrawn": "已退案",
}

# 文件名中不允许出现的字符（Content-Disposition 与 Windows 都受限）
_ILLEGAL_FILENAME_CHARS = re.compile(r'[\\/:*?"<>|\r\n\t]')


# ---------------------------------------------------------------------------
# 变量填充
# ---------------------------------------------------------------------------


def extract_var_keys(content: str | None) -> list[str]:
    """提取正文中的占位符名称（去重、保持出现顺序）。"""
    if not content:
        return []
    keys: list[str] = []
    for match in VAR_PATTERN.finditer(content):
        key = match.group(1).strip()
        if key and key not in keys:
            keys.append(key)
    return keys


def render_template(
    content: str, context: dict[str, str]
) -> tuple[str, dict[str, str], list[str]]:
    """把 ``{变量}`` 替换成上下文里的值。

    返回 ``(渲染结果, 已填充变量, 未取到值的变量)``。
    取不到值的占位符**原样保留**，由律师在编辑器里手工补全，同时通过
    ``missing`` 提示前端高亮，避免静默替换成空白导致漏填。
    """
    filled: dict[str, str] = {}
    missing: list[str] = []

    def _replace(match: re.Match[str]) -> str:
        raw = match.group(1).strip()
        key = _VAR_ALIASES.get(raw, raw)
        value = context.get(key)
        if value:
            filled[key] = value
            return value
        if key not in missing:
            missing.append(key)
        return match.group(0)

    return VAR_PATTERN.sub(_replace, content), filled, missing


def _money(value: Decimal | None) -> str:
    """金额格式化：12,345.60。"""
    if value is None:
        return ""
    return f"{value:,.2f}"


async def _firm_info(db: AsyncSession) -> dict[str, str]:
    """取律所信息（表无 ORM 模型，用原生 SQL 读取，缺失则留空）。"""
    row = (
        await db.execute(
            text("SELECT name, address, phone FROM firm_info ORDER BY id LIMIT 1")
        )
    ).first()
    if row is None:
        return {}
    return {
        "律所名称": row[0] or "",
        "律所地址": row[1] or "",
        "律所电话": row[2] or "",
    }


async def _lead_lawyer_name(db: AsyncSession, case_id: int) -> str | None:
    """案件主办律师姓名。"""
    return await db.scalar(
        select(User.real_name)
        .join(CaseLawyer, CaseLawyer.lawyer_id == User.id)
        .where(CaseLawyer.case_id == case_id, CaseLawyer.duty == "lead")
        .limit(1)
    )


async def build_template_context(
    db: AsyncSession,
    *,
    case: Case | None,
    client: ClientProfile | None,
    current: User,
) -> dict[str, str]:
    """组装模板变量取值：客户档案 + 案件字段 + 律所信息 + 日期。"""
    now = datetime.now()
    context: dict[str, str] = {
        "今日日期": f"{now.year}年{now.month}月{now.day}日",
        "年份": str(now.year),
        "月份": str(now.month),
        "日期": str(now.day),
    }
    context.update({k: v for k, v in (await _firm_info(db)).items() if v})

    if client is not None:
        context.update(
            {
                "客户姓名": client.name or "",
                "客户电话": client.phone or "",
                "客户地址": client.address or "",
                "客户证件号": client.id_no or "",
                "客户性别": client.gender or "",
            }
        )

    if case is not None:
        context.update(
            {
                "案号": case.case_no or "",
                "案件标题": case.title or "",
                "案由": case.case_cause or "",
                "受理法院": case.court or "",
                "对方当事人": case.opposing_party or "",
                "标的额": _money(case.amount),
                "案件状态": _CASE_STATUS_LABELS.get(case.status, case.status),
            }
        )

    lawyer_name = None
    if case is not None:
        lawyer_name = await _lead_lawyer_name(db, case.id)
    context["委托律师"] = lawyer_name or current.real_name or ""

    return {k: v for k, v in context.items() if v}


# ---------------------------------------------------------------------------
# 通用辅助
# ---------------------------------------------------------------------------


async def _lawyer_case_ids(db: AsyncSession, user_id: int) -> set[int]:
    """律师主办/协办的案件 id 集合。"""
    rows = (
        (
            await db.execute(
                select(CaseLawyer.case_id).where(CaseLawyer.lawyer_id == user_id)
            )
        )
        .scalars()
        .all()
    )
    return set(rows)


def _sanitize_filename(name: str, suffix: str = ".docx") -> str:
    """清理文件名中的非法字符，保证下载时浏览器能正确识别。"""
    cleaned = _ILLEGAL_FILENAME_CHARS.sub("_", (name or "文书").strip())
    return f"{cleaned[:80] or '文书'}{suffix}"


def _excerpt(content: str | None) -> str:
    """正文纯文本摘要：压平换行、截断到固定长度。"""
    plain = re.sub(r"\s+", " ", html_to_text(content)).strip()
    return plain[:EXCERPT_LENGTH] + "…" if len(plain) > EXCERPT_LENGTH else plain


def _remove_upload(rel_path: str | None) -> None:
    """尽力删除 upload 目录下的旧文件，失败不影响主流程。"""
    if not rel_path:
        return
    try:
        abs_path = (settings.upload_dir / rel_path).resolve()
        if str(abs_path).startswith(str(settings.upload_dir.resolve())):
            abs_path.unlink(missing_ok=True)
    except OSError:
        return


# ---------------------------------------------------------------------------
# 模板 CRUD
# ---------------------------------------------------------------------------


def _decorate_templates(templates: list[DocTemplate]) -> list[DocTemplate]:
    """给模板注入变量清单与正文摘要（非映射字段）。"""
    for tpl in templates:
        tpl.var_keys = extract_var_keys(tpl.content)
        tpl.excerpt = _excerpt(tpl.content)
    return templates


async def list_templates(
    db: AsyncSession,
    *,
    doc_type: str | None = None,
    keyword: str | None = None,
    page: int = 1,
    page_size: int = 100,
) -> tuple[int, list[DocTemplate]]:
    """模板列表：按类型筛选、按名称模糊搜索。"""
    if page < 1 or not 1 <= page_size <= 200:
        raise BadRequest("分页参数不合法")

    stmt = select(DocTemplate)
    if doc_type:
        stmt = stmt.where(DocTemplate.doc_type == doc_type)
    if keyword:
        stmt = stmt.where(DocTemplate.name.like(f"%{keyword.strip()}%"))

    total = await db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = (
        (
            await db.execute(
                stmt.order_by(DocTemplate.id.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        )
        .scalars()
        .all()
    )
    return int(total), _decorate_templates(list(rows))


async def get_template(db: AsyncSession, template_id: int) -> DocTemplate:
    """模板详情，不存在抛 404。"""
    template = await db.get(DocTemplate, template_id)
    if template is None:
        raise NotFound("文书模板不存在")
    return _decorate_templates([template])[0]


async def create_template(
    db: AsyncSession, payload: TemplateIn, current: User
) -> DocTemplate:
    """新建模板（律师/管理员）。"""
    if current.role not in ("lawyer", "admin"):
        raise Forbidden("无权维护文书模板")

    template = DocTemplate(
        doc_type=payload.doc_type,
        name=payload.name,
        content=payload.content,
    )
    db.add(template)
    await db.commit()
    await db.refresh(template)
    return _decorate_templates([template])[0]


async def update_template(
    db: AsyncSession, template_id: int, payload: TemplateIn, current: User
) -> DocTemplate:
    """更新模板（全量）。"""
    if current.role not in ("lawyer", "admin"):
        raise Forbidden("无权维护文书模板")

    template = await get_template(db, template_id)
    template.doc_type = payload.doc_type
    template.name = payload.name
    template.content = payload.content
    await db.commit()
    await db.refresh(template)
    return _decorate_templates([template])[0]


async def delete_template(
    db: AsyncSession, template_id: int, current: User
) -> None:
    """删除模板（不影响已生成的文书）。"""
    if current.role not in ("lawyer", "admin"):
        raise Forbidden("无权维护文书模板")
    template = await get_template(db, template_id)
    await db.delete(template)
    await db.commit()


# ---------------------------------------------------------------------------
# 文书查询与可见范围
# ---------------------------------------------------------------------------


async def _attach_refs(db: AsyncSession, docs: list[Document]) -> list[Document]:
    """批量注入案件编号/标题、客户姓名、创建人姓名与正文摘要。"""
    if not docs:
        return docs

    case_ids = {d.case_id for d in docs if d.case_id}
    if case_ids:
        rows = (
            await db.execute(
                select(Case.id, Case.case_no, Case.title).where(
                    Case.id.in_(case_ids)
                )
            )
        ).all()
        case_map = {cid: (no, title) for cid, no, title in rows}
        for doc in docs:
            if doc.case_id:
                no, title = case_map.get(doc.case_id, (None, None))
                doc.case_no = no
                doc.case_title = title

    client_ids = {d.client_id for d in docs if d.client_id}
    if client_ids:
        rows = (
            await db.execute(
                select(ClientProfile.id, ClientProfile.name).where(
                    ClientProfile.id.in_(client_ids)
                )
            )
        ).all()
        name_map = dict(rows)
        for doc in docs:
            if doc.client_id:
                doc.client_name = name_map.get(doc.client_id)

    user_ids = {d.created_by for d in docs if d.created_by}
    if user_ids:
        rows = (
            await db.execute(
                select(User.id, User.real_name).where(User.id.in_(user_ids))
            )
        ).all()
        creator_map = dict(rows)
        for doc in docs:
            if doc.created_by:
                doc.creator_name = creator_map.get(doc.created_by)

    for doc in docs:
        doc.excerpt = _excerpt(doc.content)
    return docs


def _scope_conditions(current: User, case_ids: set[int]) -> list:
    """律师可见范围：本人创建 或 本人承办案件下的文书。"""
    if current.role == "admin":
        return []
    if current.role != "lawyer":
        raise Forbidden("无权访问文书")
    conds = [Document.created_by == current.id]
    if case_ids:
        conds.append(Document.case_id.in_(case_ids))
    return [or_(*conds)]


async def _apply_scope(
    db: AsyncSession, stmt: Select, current: User
) -> Select:
    """给查询套上律师可见范围。"""
    case_ids = (
        await _lawyer_case_ids(db, current.id) if current.role == "lawyer" else set()
    )
    conds = _scope_conditions(current, case_ids)
    return stmt.where(*conds) if conds else stmt


async def list_documents(
    db: AsyncSession,
    *,
    current: User,
    case_id: int | None = None,
    doc_type: str | None = None,
    status: str | None = None,
    keyword: str | None = None,
    created_by: int | None = None,
    page: int = 1,
    page_size: int = 20,
) -> tuple[int, list[Document]]:
    """文书列表（分页），律师仅见本人或本人案件下的文书。"""
    if page < 1 or not 1 <= page_size <= 100:
        raise BadRequest("分页参数不合法")

    stmt = await _apply_scope(db, select(Document), current)
    if case_id:
        stmt = stmt.where(Document.case_id == case_id)
    if doc_type:
        stmt = stmt.where(Document.doc_type == doc_type)
    if status:
        stmt = stmt.where(Document.status == status)
    if created_by:
        stmt = stmt.where(Document.created_by == created_by)
    if keyword:
        stmt = stmt.where(Document.title.like(f"%{keyword.strip()}%"))

    total = await db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = (
        (
            await db.execute(
                stmt.order_by(Document.updated_at.desc(), Document.id.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        )
        .scalars()
        .all()
    )
    items = await _attach_refs(db, list(rows))
    return int(total), items


async def _get_document_or_404(db: AsyncSession, document_id: int) -> Document:
    """读取文书，不存在抛 404。"""
    doc = await db.get(Document, document_id)
    if doc is None:
        raise NotFound("文书不存在")
    return doc


async def _my_client_profile(db: AsyncSession, current: User) -> ClientProfile:
    """当前客户本人的客户档案（user_id 关联，手机号兜底）。"""
    if current.role != "client":
        raise Forbidden("仅客户可查看")
    cond = ClientProfile.user_id == current.id
    if current.phone:
        cond = or_(cond, ClientProfile.phone == current.phone)
    profile = await db.scalar(select(ClientProfile).where(cond).limit(1))
    if profile is None:
        raise NotFound("未找到您的客户档案，请联系承办律师")
    return profile


def _client_case_subquery(profile_id: int):
    """客户名下案件 id 子查询，兼容只填了 case_id 的历史文书。"""
    return select(Case.id).where(Case.client_id == profile_id)


async def _assert_readable(db: AsyncSession, doc: Document, current: User) -> None:
    """读权限：管理员全量、律师本人/本人案件、客户仅已发布的本人文书。"""
    if current.role == "admin":
        return
    if current.role == "lawyer":
        if doc.created_by == current.id:
            return
        if doc.case_id and doc.case_id in await _lawyer_case_ids(db, current.id):
            return
        raise Forbidden("无权查看该文书")
    if current.role == "client":
        if doc.status != "published":
            raise Forbidden("该文书尚未对客户开放")
        profile = await _my_client_profile(db, current)
        owned = doc.client_id == profile.id or (
            doc.case_id is not None
            and await db.scalar(
                select(Case.client_id).where(Case.id == doc.case_id)
            )
            == profile.id
        )
        if not owned:
            raise Forbidden("无权查看该文书")
        return
    raise Forbidden("无权查看该文书")


async def get_document(
    db: AsyncSession, document_id: int, current: User
) -> Document:
    """文书详情（含正文）。"""
    doc = await _get_document_or_404(db, document_id)
    await _assert_readable(db, doc, current)
    await _attach_refs(db, [doc])
    return doc


# ---------------------------------------------------------------------------
# 文书写操作
# ---------------------------------------------------------------------------


async def _assert_case_access(
    db: AsyncSession, case_id: int, current: User
) -> Case:
    """校验律师能在该案件下建文书（管理员不限）。"""
    case = await db.get(Case, case_id)
    if case is None:
        raise NotFound("关联案件不存在")
    if current.role == "admin":
        return case
    if current.role != "lawyer":
        raise Forbidden("无权在该案件下编辑文书")
    rel = await db.scalar(
        select(CaseLawyer.case_id).where(
            CaseLawyer.case_id == case_id, CaseLawyer.lawyer_id == current.id
        )
    )
    if rel is None:
        raise Forbidden("无权在该案件下编辑文书")
    return case


async def get_editable_case(
    db: AsyncSession, case_id: int, current: User
) -> Case:
    """取案件并校验当前用户可在其下生成/归档文书（供 9.4 AI 文书复用）。

    单独暴露一个公开函数，是为了让 ``ai_service`` 不必去调用下划线开头的
    内部实现——文书与 AI 生成用的是同一套权限规则，必须只有一处定义。
    """
    return await _assert_case_access(db, case_id, current)


async def _assert_writable(db: AsyncSession, doc: Document, current: User) -> None:
    """写权限：管理员、创建人本人、或承办该案件的律师。"""
    if current.role == "admin":
        return
    if current.role != "lawyer":
        raise Forbidden("无权操作文书")
    if doc.created_by == current.id:
        return
    if doc.case_id and doc.case_id in await _lawyer_case_ids(db, current.id):
        return
    raise Forbidden("只能管理本人或本人承办案件的文书")


async def create_document(
    db: AsyncSession, payload: DocumentIn, current: User
) -> Document:
    """新建文书：有关联案件时自动带出委托客户，便于客户端过滤。"""
    if current.role not in ("lawyer", "admin"):
        raise Forbidden("无权新建文书")

    client_id = None
    if payload.case_id is not None:
        case = await _assert_case_access(db, payload.case_id, current)
        client_id = case.client_id

    doc = Document(
        case_id=payload.case_id,
        client_id=client_id,
        doc_type=payload.doc_type,
        title=payload.title,
        content=payload.content,
        is_ai_generated=payload.is_ai_generated,
        ai_session_id=payload.ai_session_id,
        status=payload.status,
        created_by=current.id,
    )
    db.add(doc)
    await db.commit()
    await db.refresh(doc)
    await _attach_refs(db, [doc])
    return doc


async def update_document(
    db: AsyncSession, document_id: int, payload: DocumentIn, current: User
) -> Document:
    """全量更新文书（PUT）。"""
    doc = await _get_document_or_404(db, document_id)
    await _assert_writable(db, doc, current)

    client_id = None
    if payload.case_id is not None:
        case = await _assert_case_access(db, payload.case_id, current)
        client_id = case.client_id

    doc.case_id = payload.case_id
    doc.client_id = client_id
    doc.doc_type = payload.doc_type
    doc.title = payload.title
    doc.content = payload.content
    doc.is_ai_generated = payload.is_ai_generated
    doc.ai_session_id = payload.ai_session_id
    doc.status = payload.status

    await db.commit()
    await db.refresh(doc)
    await _attach_refs(db, [doc])
    return doc


async def delete_document(
    db: AsyncSession, document_id: int, current: User
) -> None:
    """删除文书，同时清理导出的 docx 与附件登记。"""
    doc = await _get_document_or_404(db, document_id)
    await _assert_writable(db, doc, current)

    attachments = (
        (
            await db.execute(
                select(Attachment).where(
                    Attachment.biz_type == "document",
                    Attachment.biz_id == document_id,
                )
            )
        )
        .scalars()
        .all()
    )
    for item in attachments:
        _remove_upload(item.file_path)
        await db.delete(item)
    if doc.file_url:
        _remove_upload(doc.file_url)

    await db.delete(doc)
    await db.commit()


# ---------------------------------------------------------------------------
# 模板生成草稿
# ---------------------------------------------------------------------------


async def generate_from_template(
    db: AsyncSession, payload: DocumentFromTemplateIn, current: User
) -> GeneratedDocOut:
    """按模板 + 案件字段生成文书草稿（不落库，供前端继续编辑）。"""
    if current.role not in ("lawyer", "admin"):
        raise Forbidden("无权生成文书")

    template = await get_template(db, payload.template_id)

    case = None
    client = None
    if payload.case_id is not None:
        case = await _assert_case_access(db, payload.case_id, current)
        client = await db.get(ClientProfile, case.client_id)

    context = await build_template_context(
        db, case=case, client=client, current=current
    )
    content, filled, missing = render_template(template.content, context)

    default_title = template.name
    if client is not None:
        default_title = f"{client.name}{template.name}"

    return GeneratedDocOut(
        template_id=template.id,
        template_name=template.name,
        case_id=case.id if case else None,
        case_no=case.case_no if case else None,
        doc_type=template.doc_type,
        doc_type_label=DOC_TYPE_LABELS.get(
            template.doc_type, template.doc_type
        ),
        title=(payload.title or default_title)[:255],
        content=content,
        filled=filled,
        missing=missing,
    )


# ---------------------------------------------------------------------------
# docx 导出 / 下载
# ---------------------------------------------------------------------------


async def _render_to_file(
    db: AsyncSession, doc: Document, current: User
) -> tuple[Path, str]:
    """把文书渲染成 docx 落盘，并登记 attachment 元信息。"""
    data = build_docx(doc.title, doc.content)

    rel_dir = Path("document") / str(doc.id)
    abs_dir = settings.upload_dir / rel_dir
    abs_dir.mkdir(parents=True, exist_ok=True)
    stored_name = f"{uuid4().hex}.docx"
    abs_path = abs_dir / stored_name
    abs_path.write_bytes(data)
    rel_path = (rel_dir / stored_name).as_posix()

    # 同一份文书只保留最新导出的文件与附件登记
    old = (
        (
            await db.execute(
                select(Attachment).where(
                    Attachment.biz_type == "document",
                    Attachment.biz_id == doc.id,
                )
            )
        )
        .scalars()
        .all()
    )
    for item in old:
        if item.file_path != rel_path:
            _remove_upload(item.file_path)
            await db.delete(item)

    doc.file_url = rel_path
    file_name = _sanitize_filename(doc.title)
    db.add(
        Attachment(
            biz_type="document",
            biz_id=doc.id,
            file_name=file_name,
            file_path=rel_path,
            file_size=len(data),
            mime_type=(
                "application/vnd.openxmlformats-officedocument."
                "wordprocessingml.document"
            ),
            uploader_id=current.id,
        )
    )
    await db.commit()
    await db.refresh(doc)
    return abs_path, file_name


async def export_document(
    db: AsyncSession, document_id: int, current: User
) -> tuple[Document, Path, str, int]:
    """导出 docx：返回 (文书, 绝对路径, 下载文件名, 文件大小)。"""
    doc = await get_document(db, document_id, current)
    abs_path, file_name = await _render_to_file(db, doc, current)
    return doc, abs_path, file_name, abs_path.stat().st_size


async def get_download(
    db: AsyncSession, document_id: int, current: User
) -> tuple[Path, str]:
    """拿到可下载的 docx 路径；未导出或文件丢失时自动重新生成。"""
    doc = await get_document(db, document_id, current)

    if doc.file_url:
        abs_path = (settings.upload_dir / doc.file_url).resolve()
        upload_root = settings.upload_dir.resolve()
        if not str(abs_path).startswith(str(upload_root)):
            raise BadRequest("非法文件路径")
        if abs_path.is_file():
            return abs_path, _sanitize_filename(doc.title)

    abs_path, file_name = await _render_to_file(db, doc, current)
    return abs_path, file_name


# ---------------------------------------------------------------------------
# 客户端：我的文书
# ---------------------------------------------------------------------------


async def list_my_documents(
    db: AsyncSession,
    *,
    current: User,
    doc_type: str | None = None,
    keyword: str | None = None,
) -> list[Document]:
    """客户端：本人案件下已发布的文书列表。"""
    profile = await _my_client_profile(db, current)

    stmt = select(Document).where(
        Document.status == "published",
        or_(
            Document.client_id == profile.id,
            Document.case_id.in_(_client_case_subquery(profile.id)),
        ),
    )
    if doc_type:
        stmt = stmt.where(Document.doc_type == doc_type)
    if keyword:
        stmt = stmt.where(Document.title.like(f"%{keyword.strip()}%"))

    rows = (
        (
            await db.execute(
                stmt.order_by(Document.created_at.desc(), Document.id.desc())
            )
        )
        .scalars()
        .all()
    )
    return await _attach_refs(db, list(rows))

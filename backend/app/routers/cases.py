"""案件管理路由：立案、列表、详情、分案、状态流转、事件登记、文件上传。"""

import re
from pathlib import Path
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Depends, Query, Request, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import select

from app.config import settings
from app.core.exceptions import BadRequest
from app.dependencies import CurrentUser, DbSession, client_ip, require_role
from app.models.user import User
from app.schemas.case import (
    AttachmentOut,
    CaseAssignIn,
    CaseCreate,
    CaseDetailOut,
    CaseEventIn,
    CaseEventOut,
    CaseLawyerOut,
    CaseListOut,
    CaseOut,
    CaseStatusIn,
)
from app.services import audit_service, case_service

router = APIRouter()

# 立案：律师、管理员均可
LawyerOrAdmin = Annotated[User, Depends(require_role("lawyer", "admin"))]
# 分案：仅管理员
AdminOnly = Annotated[User, Depends(require_role("admin"))]


@router.get(
    "/lawyers", response_model=list[CaseLawyerOut], summary="律师列表（供分案选择）"
)
async def list_lawyers(db: DbSession, user: AdminOnly) -> list[CaseLawyerOut]:
    """返回全部 lawyer 角色账号，供管理员分案时选择主办/协办律师。"""
    rows = (
        (
            await db.execute(
                select(User)
                .where(User.role == "lawyer", User.status == 1)
                .order_by(User.id)
            )
        )
        .scalars()
        .all()
    )
    return [
        CaseLawyerOut(
            lawyer_id=u.id, duty="lead", lawyer_name=u.real_name or u.username
        )
        for u in rows
    ]


@router.get("/files/{attachment_id}", summary="下载/预览案件材料")
async def download_case_file(
    attachment_id: int, db: DbSession, user: CurrentUser
) -> FileResponse:
    """按附件 id 下载案件材料，做行级权限校验。

    律师/管理员/客户均可访问本人有权限的案件附件；PDF/图片等浏览器可直接预览，
    Word 等则触发下载。``filename`` 参数用于还原中文原名。
    """
    attachment = await case_service.get_attachment(db, attachment_id, user)

    # 拼接物理路径并做目录穿越防护
    abs_path = (settings.upload_dir / attachment.file_path).resolve()
    upload_root = settings.upload_dir.resolve()
    if not str(abs_path).startswith(str(upload_root)):
        raise BadRequest("非法文件路径")
    if not abs_path.is_file():
        raise BadRequest("文件不存在或已被移除")

    return FileResponse(
        path=abs_path,
        media_type=attachment.mime_type or "application/octet-stream",
        filename=attachment.file_name,
    )


@router.get("", response_model=CaseListOut, summary="案件列表（分页）")
async def list_cases(
    db: DbSession,
    user: CurrentUser,
    status: str | None = Query(default=None, description="案件状态"),
    cause: str | None = Query(default=None, description="案由模糊搜索"),
    case_type: str | None = Query(default=None, description="诉讼/非诉"),
    lawyer_id: int | None = Query(default=None, description="承办律师（仅管理员）"),
    client_id: int | None = Query(default=None, description="委托客户ID"),
    page: int = Query(default=1, ge=1, description="页码"),
    page_size: int = Query(default=20, ge=1, le=100, description="每页数量"),
) -> CaseListOut:
    """分页查询案件，律师仅见本人主办/协办案件，管理员见全部。"""
    total, items = await case_service.list_cases(
        db,
        current=user,
        status=status,
        cause=cause,
        case_type=case_type,
        lawyer_id=lawyer_id,
        client_id=client_id,
        page=page,
        page_size=page_size,
    )
    return CaseListOut(total=total, items=[CaseOut.model_validate(x) for x in items])


@router.post("", response_model=CaseOut, summary="立案")
async def create_case(
    payload: CaseCreate, request: Request, db: DbSession, user: LawyerOrAdmin
) -> CaseOut:
    """立案：生成案号并创建案件，律师默认成为主办律师。"""
    case = await case_service.create_case(db, payload, user)
    await audit_service.write_log_safe(
        db,
        user_id=user.id,
        action=audit_service.ACTION_CREATE,
        target=f"case:{case.id}",
        detail=f"立案 {case.case_no}：{case.title}",
        ip=client_ip(request),
    )
    return case


@router.get("/{case_id}", response_model=CaseDetailOut, summary="案件详情")
async def get_case_detail(
    case_id: int, db: DbSession, user: CurrentUser
) -> CaseDetailOut:
    """案件详情：基本信息 + 承办律师 + 时间线 + 关联附件。"""
    case = await case_service.get_case_detail(db, case_id, user)

    # 聚合承办律师（含姓名）
    lawyer_rows = await case_service.list_case_lawyers(db, case_id)
    lawyers = [
        CaseLawyerOut(lawyer_id=rel.lawyer_id, duty=rel.duty, lawyer_name=name)
        for rel, name in lawyer_rows
    ]

    # 聚合时间线
    events = [
        CaseEventOut.model_validate(e)
        for e in await case_service.list_case_events(db, case_id)
    ]

    # 聚合附件
    attachments = [
        AttachmentOut.model_validate(a)
        for a in await case_service.list_case_attachments(db, case_id)
    ]
    for a in attachments:
        a.download_url = f"/api/cases/files/{a.id}"

    detail = CaseDetailOut.model_validate(case)
    detail.lawyers = lawyers
    detail.events = events
    detail.attachments = attachments
    return detail


@router.delete("/{case_id}", status_code=204, summary="删除案件")
async def delete_case(
    case_id: int, request: Request, db: DbSession, user: AdminOnly
) -> None:
    """删除案件（仅管理员），级联清理承办关系、事件与附件。"""
    await case_service.delete_case(db, case_id, user)
    await audit_service.write_log_safe(
        db,
        user_id=user.id,
        action=audit_service.ACTION_DELETE,
        target=f"case:{case_id}",
        detail=f"删除案件 #{case_id}",
        ip=client_ip(request),
    )


@router.post("/{case_id}/assign", summary="分案（管理员）")
async def assign_case(
    case_id: int,
    payload: CaseAssignIn,
    request: Request,
    db: DbSession,
    user: AdminOnly,
) -> list[CaseLawyerOut]:
    """分案：管理员指定主办律师与协办律师（覆盖式）。"""
    rels = await case_service.assign_case(db, case_id, payload, user)

    # 补姓名
    result = []
    for rel in rels:
        lawyer = await db.get(User, rel.lawyer_id)
        result.append(
            CaseLawyerOut(
                lawyer_id=rel.lawyer_id,
                duty=rel.duty,
                lawyer_name=lawyer.real_name if lawyer else None,
            )
        )

    await audit_service.write_log_safe(
        db,
        user_id=user.id,
        action=audit_service.ACTION_UPDATE,
        target=f"case:{case_id}",
        detail="分案：主办+协办律师调整",
        ip=client_ip(request),
    )
    return result


@router.patch("/{case_id}/status", response_model=CaseOut, summary="状态流转")
async def update_case_status(
    case_id: int,
    payload: CaseStatusIn,
    request: Request,
    db: DbSession,
    user: LawyerOrAdmin,
) -> CaseOut:
    """状态流转：校验状态机合法性，结案写 closed_at。"""
    case = await case_service.update_case_status(db, case_id, payload, user)
    await audit_service.write_log_safe(
        db,
        user_id=user.id,
        action=audit_service.ACTION_UPDATE,
        target=f"case:{case.id}",
        detail=f"案件状态流转 → {case.status}",
        ip=client_ip(request),
    )
    return case


@router.post("/{case_id}/events", response_model=CaseEventOut, summary="登记案件事件")
async def add_case_event(
    case_id: int,
    payload: CaseEventIn,
    request: Request,
    db: DbSession,
    user: LawyerOrAdmin,
) -> CaseEventOut:
    """登记案件事件，写入时间线。"""
    event = await case_service.add_case_event(db, case_id, payload, user)
    await audit_service.write_log_safe(
        db,
        user_id=user.id,
        action=audit_service.ACTION_CREATE,
        target=f"case:{case_id}",
        detail=f"登记事件 {event.event_type}",
        ip=client_ip(request),
    )
    return event


@router.post("/{case_id}/files", response_model=AttachmentOut, summary="上传案件文件")
async def upload_case_file(
    case_id: int,
    file: UploadFile,
    request: Request,
    db: DbSession,
    user: LawyerOrAdmin,
) -> AttachmentOut:
    """上传证据/文书到案件，落盘到 upload 目录并登记附件。

    保存路径：``uploads/case/{case_id}/{uuid}.{ext}``，返回附件元信息。
    """
    # 安全校验：文件大小上限
    content = await file.read()
    if len(content) > settings.max_upload_size:
        raise BadRequest(
            f"文件大小超过 {settings.max_upload_size // (1024 * 1024)}MB 上限"
        )

    # 生成唯一存储名，保留原始扩展名
    original_name = file.filename or "未命名文件"
    ext = Path(original_name).suffix.lower()
    if not ext:
        ext = _guess_ext(file.content_type)
    safe_ext = ext if re.fullmatch(r"\.[a-zA-Z0-9]{1,10}", ext) else ""
    stored_name = f"{uuid4().hex}{safe_ext}"
    rel_dir = Path("case") / str(case_id)
    abs_dir = settings.upload_dir / rel_dir
    abs_dir.mkdir(parents=True, exist_ok=True)
    abs_path = abs_dir / stored_name
    abs_path.write_bytes(content)

    rel_path = (rel_dir / stored_name).as_posix()
    attachment = await case_service.save_case_file(
        db,
        case_id=case_id,
        original_name=original_name,
        stored_path=rel_path,
        file_size=len(content),
        mime_type=file.content_type,
        current=user,
    )

    await audit_service.write_log_safe(
        db,
        user_id=user.id,
        action=audit_service.ACTION_CREATE,
        target=f"case:{case_id}",
        detail=f"上传文件 {original_name}",
        ip=client_ip(request),
    )
    return attachment


# 常见扩展名兜底（content_type → 扩展名）
_MIME_EXT = {
    "application/pdf": ".pdf",
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "application/msword": ".doc",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    "text/plain": ".txt",
}


def _guess_ext(content_type: str | None) -> str:
    return _MIME_EXT.get(content_type or "", ".bin")

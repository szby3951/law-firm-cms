"""沟通留言路由：发送留言、会话列表、会话记录、标记已读、附件上传/下载。

权限：客户与律师走同一组接口，服务层按登录身份做行级隔离——
客户只能和自己的承办律师沟通，律师只能与本人负责的客户沟通，管理员可兜底。
客户端另有 ``/api/my/messages`` 便于「我的留言」页直接取数据。
"""

import re
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, Query, Request, UploadFile
from fastapi.responses import FileResponse

from app.config import settings
from app.core.exceptions import BadRequest
from app.dependencies import CurrentUser, DbSession, client_ip
from app.schemas.case import AttachmentOut
from app.schemas.message import (
    ConversationListOut,
    MessageCreate,
    MessageListOut,
    MessageOut,
    MessageReadOut,
    MessageUnreadOut,
)
from app.services import audit_service, message_service

router = APIRouter()

# 常见扩展名兜底（content_type → 扩展名）
_MIME_EXT = {
    "application/pdf": ".pdf",
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/gif": ".gif",
    "application/msword": ".doc",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    "application/vnd.ms-excel": ".xls",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
    "text/plain": ".txt",
}


def _guess_ext(content_type: str | None) -> str:
    return _MIME_EXT.get(content_type or "", ".bin")


def _with_download_url(att) -> AttachmentOut:
    """补上下载地址，前端可直接点击/预览。"""
    out = AttachmentOut.model_validate(att)
    out.download_url = f"/api/messages/files/{att.id}"
    return out


# ---------------------------------------------------------------------------
# 会话
# ---------------------------------------------------------------------------


@router.get("/conversations", response_model=ConversationListOut, summary="会话列表")
async def list_conversations(
    db: DbSession,
    user: CurrentUser,
    keyword: str | None = Query(default=None, description="对方姓名关键词"),
    only_unread: bool = Query(default=False, description="仅看有未读的会话"),
) -> ConversationListOut:
    """律师按客户聚合、客户按律师聚合的会话列表（含未读数）。"""
    return await message_service.list_conversations(
        db, current=user, keyword=keyword, only_unread=only_unread
    )


@router.get("/unread-count", response_model=MessageUnreadOut, summary="未读留言数")
async def unread_count(db: DbSession, user: CurrentUser) -> MessageUnreadOut:
    """红点用：发给我的未读留言条数。"""
    return MessageUnreadOut(count=await message_service.count_unread(db, user))


@router.patch(
    "/conversations/{client_id}/read",
    response_model=MessageReadOut,
    summary="会话全部标记已读",
)
async def read_conversation(
    client_id: int, db: DbSession, user: CurrentUser
) -> MessageReadOut:
    """把一个会话里对方发来的未读留言一次性置为已读。"""
    updated = await message_service.mark_conversation_read(
        db, current=user, client_id=client_id
    )
    return MessageReadOut(updated=updated)


@router.patch("/read-all", response_model=MessageReadOut, summary="全部标记已读")
async def read_all(db: DbSession, user: CurrentUser) -> MessageReadOut:
    """把发给我的全部未读留言置为已读。"""
    return MessageReadOut(updated=await message_service.mark_all_read(db, user))


# ---------------------------------------------------------------------------
# 附件
# ---------------------------------------------------------------------------


@router.get("/files/{attachment_id}", summary="下载/预览留言附件")
async def download_attachment(
    attachment_id: int, db: DbSession, user: CurrentUser
) -> FileResponse:
    """按附件 id 下载或预览（图片/PDF 浏览器可直接打开）。"""
    att = await message_service.get_attachment(db, attachment_id, user)

    # 拼接物理路径并做目录穿越防护
    abs_path = (settings.upload_dir / att.file_path).resolve()
    upload_root = settings.upload_dir.resolve()
    if not str(abs_path).startswith(str(upload_root)):
        raise BadRequest("非法文件路径")
    if not abs_path.is_file():
        raise BadRequest("文件不存在或已被移除")

    return FileResponse(
        path=abs_path,
        media_type=att.mime_type or "application/octet-stream",
        filename=att.file_name,
    )


# ---------------------------------------------------------------------------
# 留言
# ---------------------------------------------------------------------------


@router.get("", response_model=MessageListOut, summary="会话记录")
async def list_messages(
    db: DbSession,
    user: CurrentUser,
    client_id: int | None = Query(default=None, description="会话客户ID"),
    lawyer_id: int | None = Query(default=None, description="会话律师ID"),
    page: int = Query(default=1, ge=1, description="页码（1 = 最新一屏）"),
    page_size: int = Query(default=50, ge=1, le=100, description="每页数量"),
) -> MessageListOut:
    """按客户（可选律师）查看双向沟通记录，按时间正序返回。

    律师调用必须带 ``client_id``；客户调用可省略（默认看自己的会话）。
    """
    return await message_service.list_messages(
        db,
        current=user,
        client_id=client_id,
        lawyer_id=lawyer_id,
        page=page,
        page_size=page_size,
    )


@router.post("", response_model=MessageOut, summary="发送留言")
async def send_message(
    payload: MessageCreate,
    request: Request,
    db: DbSession,
    user: CurrentUser,
) -> MessageOut:
    """发送留言：客户 → 律师 / 律师 → 客户，自动推导会话对方。"""
    msg = await message_service.send_message(db, payload, user)
    role_label = "客户" if msg.sender_role == "client" else "律师"
    await audit_service.write_log_safe(
        db,
        user_id=user.id,
        action=audit_service.ACTION_CREATE,
        target=f"message:{msg.id}",
        detail=f"{role_label}发送留言（客户 #{msg.client_id}）",
        ip=client_ip(request),
    )
    return MessageOut.model_validate(msg)


@router.patch("/{message_id}/read", response_model=MessageOut, summary="标记已读")
async def mark_read(message_id: int, db: DbSession, user: CurrentUser) -> MessageOut:
    """标记单条留言已读（只能标记对方发来的，自己发的原样返回）。"""
    msg = await message_service.mark_read(db, message_id, user)
    return MessageOut.model_validate(msg)


@router.delete("/{message_id}", response_model=MessageOut, summary="撤回 / 删除留言")
async def delete_message(
    message_id: int, request: Request, db: DbSession, user: CurrentUser
) -> MessageOut:
    """撤回或删除一条留言（软删除）。

    - 发送人本人：只能撤回自己发出的、5 分钟内的留言；
    - 管理员：可删除任意留言（违规内容 / 质检清理），不受时间限制。

    返回删除后的留言占位（``is_deleted=true`` + ``placeholder`` 文案），
    前端直接用它替换原气泡，无需整段重新拉取。
    """
    msg = await message_service.delete_message(db, message_id, user)
    is_admin_remove = msg.delete_kind == "admin"
    await audit_service.write_log_safe(
        db,
        user_id=user.id,
        action=audit_service.ACTION_DELETE,
        target=f"message:{message_id}",
        detail=(
            f"{'管理员删除' if is_admin_remove else '发送人撤回'}留言"
            f"（客户 #{msg.client_id}）"
        ),
        ip=client_ip(request),
    )
    return MessageOut.model_validate(msg)


@router.get(
    "/{message_id}/attachments",
    response_model=list[AttachmentOut],
    summary="留言附件列表",
)
async def list_attachments(
    message_id: int, db: DbSession, user: CurrentUser
) -> list[AttachmentOut]:
    """查看某条留言的附件。"""
    rows = await message_service.list_message_attachments(db, message_id, user)
    return [_with_download_url(a) for a in rows]


@router.post(
    "/{message_id}/attachment",
    response_model=AttachmentOut,
    summary="上传留言附件",
)
async def upload_attachment(
    message_id: int,
    file: UploadFile,
    request: Request,
    db: DbSession,
    user: CurrentUser,
) -> AttachmentOut:
    """给已有留言补传材料（图片/PDF 等）。

    保存路径：``uploads/message/{message_id}/{uuid}.{ext}``。
    """
    content = await file.read()
    if not content:
        raise BadRequest("文件内容为空")
    if len(content) > settings.max_upload_size:
        raise BadRequest(
            f"文件大小超过 {settings.max_upload_size // (1024 * 1024)}MB 上限"
        )

    original_name = file.filename or "未命名文件"
    ext = Path(original_name).suffix.lower()
    if not ext:
        ext = _guess_ext(file.content_type)
    safe_ext = ext if re.fullmatch(r"\.[a-zA-Z0-9]{1,10}", ext) else ""
    stored_name = f"{uuid4().hex}{safe_ext}"
    rel_dir = Path("message") / str(message_id)
    abs_dir = settings.upload_dir / rel_dir
    abs_dir.mkdir(parents=True, exist_ok=True)
    abs_path = abs_dir / stored_name
    abs_path.write_bytes(content)

    rel_path = (rel_dir / stored_name).as_posix()
    att = await message_service.save_attachment(
        db,
        message_id,
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
        target=f"message:{message_id}",
        detail=f"上传留言附件 {original_name}",
        ip=client_ip(request),
    )
    return _with_download_url(att)

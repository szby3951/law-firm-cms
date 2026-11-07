"""沟通留言业务逻辑：发送留言、会话列表、会话记录、标记已读、附件。

会话键 = ``(client_id, lawyer_id)``。``message.lawyer_id`` 始终记录会话的
律师一方（不是「本条的接收人」），因此两个方向的消息可以用同一条件聚合。

``is_read`` 表示**对方**是否已读：客户发的 → 律师读后置 1；律师发的 →
客户读后置 1。

权限（对应任务拆解 8.1.4「客户只能和自己律师沟通」）：

- 客户：只能与自己的承办律师沟通（客户档案 owner 律师，或本人任一案件的
  承办律师）；读取时也只看得到自己的会话；
- 律师：只能与本人负责的客户沟通（客户档案 owner 是自己，或客户名下有
  自己承办的案件）；
- 管理员：可查看、回复全部会话（用于兜底接待与质检）。
"""

from datetime import datetime, timedelta

from sqlalchemy import Select, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BadRequest, Forbidden, NotFound
from app.models.attachment import Attachment
from app.models.case import Case
from app.models.case_lawyer import CaseLawyer
from app.models.client import ClientProfile
from app.models.message import Message
from app.models.user import User
from app.schemas.case import AttachmentOut
from app.schemas.message import (
    DELETE_KIND_TEXT,
    ConversationListOut,
    ConversationOut,
    MessageCreate,
    MessageListOut,
    MessageOut,
)

# 会话列表里最后一条消息的摘要长度
EXCERPT_LENGTH = 60

# 发送人本人撤回的时间窗口（分钟）。超过之后只能由管理员在后台删除，
# 与微信「2 分钟内撤回」同理：给手滑留余地，又不让人随意改写历史记录。
RECALL_WINDOW_MINUTES = 5


# ---------------------------------------------------------------------------
# 权限与范围推导
# ---------------------------------------------------------------------------


async def _client_profile(db: AsyncSession, current: User) -> ClientProfile:
    """当前客户的客户档案（user_id 关联，手机号兜底）。"""
    if current.role != "client":
        raise Forbidden("仅客户可查看")
    cond = ClientProfile.user_id == current.id
    if current.phone:
        cond = or_(cond, ClientProfile.phone == current.phone)
    profile = await db.scalar(select(ClientProfile).where(cond).limit(1))
    if profile is None:
        raise NotFound("未找到您的客户档案，请联系承办律师")
    return profile


async def _lawyer_scope_client_ids(db: AsyncSession, lawyer_id: int) -> set[int]:
    """律师可沟通的客户：客户档案 owner + 本人承办案件的委托客户。"""
    owned = select(ClientProfile.id).where(ClientProfile.lawyer_id == lawyer_id)
    via_case = (
        select(Case.client_id)
        .join(CaseLawyer, CaseLawyer.case_id == Case.id)
        .where(CaseLawyer.lawyer_id == lawyer_id)
    )
    rows = await db.execute(owned.union(via_case))
    return {int(x) for x in rows.scalars().all() if x is not None}


async def _client_lawyer_ids(db: AsyncSession, profile: ClientProfile) -> set[int]:
    """客户可沟通的律师：客户档案 owner + 本人案件的承办律师。"""
    ids: set[int] = set()
    if profile.lawyer_id:
        ids.add(int(profile.lawyer_id))
    rows = await db.execute(
        select(CaseLawyer.lawyer_id)
        .join(Case, Case.id == CaseLawyer.case_id)
        .where(Case.client_id == profile.id)
    )
    ids |= {int(x) for x in rows.scalars().all() if x is not None}
    return ids


async def _lead_lawyer_id(db: AsyncSession, case_id: int) -> int | None:
    """案件的主办律师（没有主办则取任一承办律师）。"""
    lead = await db.scalar(
        select(CaseLawyer.lawyer_id)
        .where(CaseLawyer.case_id == case_id, CaseLawyer.duty == "lead")
        .limit(1)
    )
    if lead:
        return int(lead)
    any_lawyer = await db.scalar(
        select(CaseLawyer.lawyer_id).where(CaseLawyer.case_id == case_id).limit(1)
    )
    return int(any_lawyer) if any_lawyer else None


async def _get_message_or_404(db: AsyncSession, message_id: int) -> Message:
    msg = await db.get(Message, message_id)
    if msg is None:
        raise NotFound("留言不存在")
    return msg


async def _assert_participant(db: AsyncSession, msg: Message, current: User) -> None:
    """校验当前用户是不是这条会话的参与方（或管理员）。"""
    if current.role == "admin":
        return
    if current.role == "lawyer":
        if msg.lawyer_id == current.id:
            return
        raise Forbidden("无权操作该会话")
    profile = await _client_profile(db, current)
    if msg.client_id == profile.id:
        return
    raise Forbidden("无权操作该会话")


async def _resolve_view(
    db: AsyncSession,
    current: User,
    *,
    client_id: int | None,
    lawyer_id: int | None,
) -> tuple[list, int | None, int | None]:
    """按角色推导会话过滤条件，返回 ``(conds, client_id, lawyer_id)``。"""
    if current.role == "client":
        profile = await _client_profile(db, current)
        conds: list = [Message.client_id == profile.id]
        if lawyer_id:
            conds.append(Message.lawyer_id == lawyer_id)
        return conds, profile.id, lawyer_id

    if current.role == "lawyer":
        if client_id is None:
            raise BadRequest("请指定客户")
        scope = await _lawyer_scope_client_ids(db, current.id)
        if client_id not in scope:
            raise Forbidden("该客户不在您的服务范围内")
        conds = [Message.client_id == client_id, Message.lawyer_id == current.id]
        return conds, client_id, current.id

    # 管理员：可按客户/律师过滤
    if client_id is None and lawyer_id is None:
        raise BadRequest("请指定客户或律师")
    conds = []
    if client_id:
        conds.append(Message.client_id == client_id)
    if lawyer_id:
        conds.append(Message.lawyer_id == lawyer_id)
    return conds, client_id, lawyer_id


async def _user_name(db: AsyncSession, user_id: int | None) -> str | None:
    """取用户姓名（律师/管理员），没有则退回账号名。"""
    if not user_id:
        return None
    row = (
        await db.execute(
            select(User.real_name, User.username).where(User.id == user_id)
        )
    ).first()
    if row is None:
        return None
    return row[0] or row[1]


async def _client_name(db: AsyncSession, client_id: int | None) -> str | None:
    if not client_id:
        return None
    return await db.scalar(
        select(ClientProfile.name).where(ClientProfile.id == client_id)
    )


# ---------------------------------------------------------------------------
# 序列化装饰
# ---------------------------------------------------------------------------


async def _decorate(
    db: AsyncSession, msgs: list[Message], current: User
) -> list[Message]:
    """批量补齐客户名/律师名/发送人名/案号/附件，避免 N+1 查询。"""
    if not msgs:
        return msgs

    now = datetime.now()

    client_ids = {m.client_id for m in msgs if m.client_id}
    lawyer_ids = {m.lawyer_id for m in msgs if m.lawyer_id}
    sender_ids = {m.sender_id for m in msgs if m.sender_id}
    case_ids = {m.case_id for m in msgs if m.case_id}
    msg_ids = [m.id for m in msgs]

    clients: dict[int, str] = {}
    if client_ids:
        rows = await db.execute(
            select(ClientProfile.id, ClientProfile.name).where(
                ClientProfile.id.in_(client_ids)
            )
        )
        clients = {int(i): n for i, n in rows.all()}

    users: dict[int, str] = {}
    user_ids = lawyer_ids | sender_ids
    if user_ids:
        rows = await db.execute(
            select(User.id, User.real_name, User.username).where(User.id.in_(user_ids))
        )
        users = {int(i): (real or name) for i, real, name in rows.all()}

    cases: dict[int, str] = {}
    if case_ids:
        rows = await db.execute(
            select(Case.id, Case.case_no).where(Case.id.in_(case_ids))
        )
        cases = {int(i): no for i, no in rows.all()}

    atts_by_msg: dict[int, list[AttachmentOut]] = {}
    if msg_ids:
        rows = await db.execute(
            select(Attachment)
            .where(Attachment.biz_type == "message", Attachment.biz_id.in_(msg_ids))
            .order_by(Attachment.id)
        )
        for att in rows.scalars().all():
            out = AttachmentOut.model_validate(att)
            out.download_url = f"/api/messages/files/{att.id}"
            atts_by_msg.setdefault(att.biz_id, []).append(out)

    for m in msgs:
        m.client_name = clients.get(m.client_id)
        m.lawyer_name = users.get(m.lawyer_id) if m.lawyer_id else None
        m.case_no = cases.get(m.case_id) if m.case_id else None
        m.sender_name = (
            clients.get(m.client_id)
            if m.sender_role == "client"
            else users.get(m.sender_id)
        )
        m.attachments = atts_by_msg.get(m.id, [])
        m.is_mine = m.sender_id == current.id
        # 撤回窗口只对「本人发的、未删除的」消息开放；管理员删除走另一条路径
        m.recallable = bool(
            not m.is_deleted
            and m.is_mine
            and m.created_at is not None
            and now - m.created_at <= timedelta(minutes=RECALL_WINDOW_MINUTES)
        )
        m.delete_kind = None
        if m.is_deleted:
            # deleted_by 等于发送人 → 本人撤回；否则是管理员在后台删除
            m.delete_kind = "recall" if m.deleted_by == m.sender_id else "admin"
    return msgs


def _excerpt(text: str | None) -> str | None:
    """会话列表摘要：压掉换行、超长截断。"""
    if not text:
        return None
    flat = " ".join(text.split())
    if len(flat) <= EXCERPT_LENGTH:
        return flat
    return flat[:EXCERPT_LENGTH] + "…"


# ---------------------------------------------------------------------------
# 8.1.3 发送留言
# ---------------------------------------------------------------------------


async def send_message(
    db: AsyncSession, payload: MessageCreate, current: User
) -> Message:
    """发送一条留言：客户 → 律师，或律师 → 客户。

    客户方向自动推导承办律师；律师方向自动把会话律师锁定为本人，
    避免消息串到别人负责的客户上。
    """
    if current.role == "client":
        profile = await _client_profile(db, current)
        client_id = profile.id
        allowed = await _client_lawyer_ids(db, profile)

        if payload.lawyer_id:
            if payload.lawyer_id not in allowed:
                raise Forbidden("该律师不是您的承办律师，无法发送留言")
            lawyer_id: int | None = payload.lawyer_id
        elif profile.lawyer_id:
            lawyer_id = int(profile.lawyer_id)
        elif payload.case_id:
            lawyer_id = await _lead_lawyer_id(db, payload.case_id)
        else:
            lawyer_id = next(iter(allowed), None)
        if lawyer_id is None:
            raise BadRequest("尚未为您分配承办律师，暂无法发送留言")
        sender_role = "client"
    elif current.role == "lawyer":
        if not payload.client_id:
            raise BadRequest("请选择沟通的客户")
        profile = await db.get(ClientProfile, payload.client_id)
        if profile is None:
            raise NotFound("客户不存在")
        scope = await _lawyer_scope_client_ids(db, current.id)
        if profile.id not in scope:
            raise Forbidden("该客户不在您的服务范围内")
        client_id = profile.id
        lawyer_id = current.id
        sender_role = "lawyer"
    else:  # admin
        if not payload.client_id:
            raise BadRequest("请选择沟通的客户")
        profile = await db.get(ClientProfile, payload.client_id)
        if profile is None:
            raise NotFound("客户不存在")
        client_id = profile.id
        lawyer_id = payload.lawyer_id or profile.lawyer_id or current.id
        sender_role = "lawyer"

    # 关联案件必须属于该客户，避免把 A 客户的案件挂到 B 客户的会话上
    if payload.case_id:
        owner = await db.scalar(
            select(Case.client_id).where(Case.id == payload.case_id)
        )
        if owner is None:
            raise NotFound("关联案件不存在")
        if int(owner) != client_id:
            raise BadRequest("该案件不属于当前客户")

    msg = Message(
        case_id=payload.case_id,
        client_id=client_id,
        lawyer_id=lawyer_id,
        sender_id=current.id,
        sender_role=sender_role,
        content=payload.content,
        is_read=False,
    )
    db.add(msg)
    await db.commit()
    await db.refresh(msg)
    await _decorate(db, [msg], current)
    return msg


# ---------------------------------------------------------------------------
# 8.1.3 会话列表 / 会话记录
# ---------------------------------------------------------------------------


async def list_conversations(
    db: AsyncSession,
    *,
    current: User,
    keyword: str | None = None,
    only_unread: bool = False,
) -> ConversationListOut:
    """会话列表。

    - 律师视角：按客户聚合（``lawyer_id = 本人``），展示客户名与最后一条消息；
    - 客户视角：按律师聚合（``client_id = 本人档案``），展示律师名；
    - 管理员：按客户聚合全所会话。
    """
    if current.role == "client":
        profile = await _client_profile(db, current)
        conds: list = [Message.client_id == profile.id]
        key_col = Message.lawyer_id
        my_role = "lawyer"  # 「对方」是律师
    else:
        conds = []
        if current.role == "lawyer":
            conds = [Message.lawyer_id == current.id]
        key_col = Message.client_id
        my_role = "client"  # 「对方」是客户

    # 1) 按会话键聚合：总条数 + 最后一条消息 id
    agg = (
        select(
            key_col.label("peer_id"),
            func.count().label("cnt"),
            func.max(Message.id).label("last_id"),
        )
        .where(*conds)
        .group_by(key_col)
    )
    agg_rows = (await db.execute(agg)).all()
    if not agg_rows:
        return ConversationListOut(total=0, unread=0, items=[])

    last_ids = [int(r.last_id) for r in agg_rows]
    last_msgs = (
        (
            await db.execute(
                select(Message)
                .where(Message.id.in_(last_ids))
                .order_by(Message.id.desc())
            )
        )
        .scalars()
        .all()
    )
    await _decorate(db, list(last_msgs), current)
    last_by_id = {m.id: m for m in last_msgs}

    # 2) 每个会话的未读条数（只算对方发来的、未撤回的）
    unread_rows = await db.execute(
        select(key_col.label("peer_id"), func.count())
        .where(
            *conds,
            Message.sender_role == my_role,
            Message.is_read.is_(False),
            Message.is_deleted.is_(False),
        )
        .group_by(key_col)
    )
    unread_map = {int(k): int(c) for k, c in unread_rows.all()}

    items: list[ConversationOut] = []
    for row in agg_rows:
        peer_id = int(row.peer_id) if row.peer_id is not None else None
        last = last_by_id.get(int(row.last_id))
        if last is None:
            continue
        items.append(
            ConversationOut(
                client_id=last.client_id,
                client_name=last.client_name,
                lawyer_id=last.lawyer_id,
                lawyer_name=last.lawyer_name,
                case_no=last.case_no,
                last_content=(
                    DELETE_KIND_TEXT.get(last.delete_kind or "recall")
                    if last.is_deleted
                    else _excerpt(last.content)
                ),
                last_sender_role=last.sender_role,
                last_at=last.created_at,
                unread=unread_map.get(peer_id, 0) if peer_id is not None else 0,
                total=int(row.cnt),
            )
        )

    # 3) 过滤（关键词按对方名称匹配）
    if keyword:
        kw = keyword.strip()
        if kw:
            items = [
                x
                for x in items
                if kw in (x.client_name or "") or kw in (x.lawyer_name or "")
            ]
    if only_unread:
        items = [x for x in items if x.unread > 0]

    items.sort(key=lambda x: x.last_at, reverse=True)
    return ConversationListOut(
        total=len(items),
        unread=sum(x.unread for x in items),
        items=items,
    )


async def list_messages(
    db: AsyncSession,
    *,
    current: User,
    client_id: int | None = None,
    lawyer_id: int | None = None,
    page: int = 1,
    page_size: int = 50,
) -> MessageListOut:
    """一段会话的消息记录（按时间正序返回，分页从最新一屏往前取）。"""
    if page < 1 or not 1 <= page_size <= 100:
        raise BadRequest("分页参数不合法")

    conds, cid, lid = await _resolve_view(
        db, current, client_id=client_id, lawyer_id=lawyer_id
    )
    base: Select = select(Message).where(*conds)

    total = int(await db.scalar(select(func.count()).select_from(base.subquery())) or 0)

    # 未读只算对方发来的，自己发的不计入
    my_role = "client" if current.role == "client" else "lawyer"
    other_role = "lawyer" if my_role == "client" else "client"
    unread = int(
        await db.scalar(
            select(func.count()).where(
                *conds,
                Message.sender_role == other_role,
                Message.is_read.is_(False),
                Message.is_deleted.is_(False),
            )
        )
        or 0
    )

    rows = (
        (
            await db.execute(
                base.order_by(Message.created_at.desc(), Message.id.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        )
        .scalars()
        .all()
    )
    # 分页时按「最新一屏」取，回卷成正序给前端直接渲染
    items = list(reversed(list(rows)))
    await _decorate(db, items, current)

    # 客户视角没传 lawyer_id、管理员按律师过滤时，用消息本身补全会话双方
    if items:
        cid = cid or items[-1].client_id
        lid = lid or items[-1].lawyer_id

    return MessageListOut(
        total=total,
        unread=unread,
        client_id=cid,
        client_name=await _client_name(db, cid),
        lawyer_id=lid,
        lawyer_name=await _user_name(db, lid),
        items=[MessageOut.model_validate(m) for m in items],
    )


# ---------------------------------------------------------------------------
# 8.1.3 已读
# ---------------------------------------------------------------------------


async def mark_read(db: AsyncSession, message_id: int, current: User) -> Message:
    """把某条留言标记为已读（只能标记对方发来的）。"""
    msg = await _get_message_or_404(db, message_id)
    await _assert_participant(db, msg, current)

    # 自己发的消息已读状态无意义，直接原样返回，保证接口幂等；
    # 已撤回/删除的留言同样不再改状态
    if msg.sender_id != current.id and not msg.is_read and not msg.is_deleted:
        msg.is_read = True
        await db.commit()
        await db.refresh(msg)
    await _decorate(db, [msg], current)
    return msg


async def mark_conversation_read(
    db: AsyncSession, *, current: User, client_id: int | None = None
) -> int:
    """把一个会话里对方发来的未读留言全部置为已读，返回更新条数。

    客户调用时 ``client_id`` 可省略（只能是自己的会话）。
    """
    if current.role == "client":
        profile = await _client_profile(db, current)
        conds: list = [
            Message.client_id == profile.id,
            Message.sender_role == "lawyer",
            Message.is_read.is_(False),
        ]
    elif current.role == "lawyer":
        if client_id is None:
            raise BadRequest("请指定客户")
        scope = await _lawyer_scope_client_ids(db, current.id)
        if client_id not in scope:
            raise Forbidden("该客户不在您的服务范围内")
        conds = [
            Message.client_id == client_id,
            Message.lawyer_id == current.id,
            Message.sender_role == "client",
            Message.is_read.is_(False),
        ]
    else:
        if client_id is None:
            raise BadRequest("请指定客户")
        conds = [
            Message.client_id == client_id,
            Message.sender_role == "client",
            Message.is_read.is_(False),
        ]

    result = await db.execute(
        update(Message)
        .where(*conds, Message.is_deleted.is_(False))
        .values(is_read=True)
    )
    await db.commit()
    return int(result.rowcount or 0)


async def mark_all_read(db: AsyncSession, current: User) -> int:
    """把「发给我的」全部未读留言置为已读（律师端一键清红点）。"""
    if current.role == "client":
        profile = await _client_profile(db, current)
        conds: list = [
            Message.client_id == profile.id,
            Message.sender_role == "lawyer",
            Message.is_read.is_(False),
        ]
    elif current.role == "lawyer":
        conds = [
            Message.lawyer_id == current.id,
            Message.sender_role == "client",
            Message.is_read.is_(False),
        ]
    else:
        conds = [Message.sender_role == "client", Message.is_read.is_(False)]

    result = await db.execute(
        update(Message)
        .where(*conds, Message.is_deleted.is_(False))
        .values(is_read=True)
    )
    await db.commit()
    return int(result.rowcount or 0)


async def count_unread(db: AsyncSession, current: User) -> int:
    """未读留言数（只算发给我的）。"""
    if current.role == "client":
        profile = await _client_profile(db, current)
        conds: list = [
            Message.client_id == profile.id,
            Message.sender_role == "lawyer",
            Message.is_read.is_(False),
        ]
    elif current.role == "lawyer":
        conds = [
            Message.lawyer_id == current.id,
            Message.sender_role == "client",
            Message.is_read.is_(False),
        ]
    else:
        conds = [Message.sender_role == "client", Message.is_read.is_(False)]

    value = await db.scalar(
        select(func.count()).where(*conds, Message.is_deleted.is_(False))
    )
    return int(value or 0)


# ---------------------------------------------------------------------------
# 8.1.3 撤回 / 删除
# ---------------------------------------------------------------------------


async def delete_message(db: AsyncSession, message_id: int, current: User) -> Message:
    """撤回或删除一条留言（软删除）。

    两条路径：

    - **本人撤回**：只能撤回自己发出的、且不超过 ``RECALL_WINDOW_MINUTES``
      分钟的留言；给手滑留余地，又不让人随意改写历史；
    - **管理员删除**：管理员可删除任意留言（违规内容、质检清理），不受时间限制。

    两条路径都只置 ``is_deleted``，正文与附件**留在库里备查**（审计需要）。
    对方刷新会话会看到「该留言已撤回 / 已被管理员删除」的占位，
    而不是记录凭空消失——否则对方会以为是自己漏看了。
    """
    msg = await _get_message_or_404(db, message_id)
    if msg.is_deleted:
        raise BadRequest("该留言已撤回或删除，无需重复操作")

    if current.role != "admin":
        await _assert_participant(db, msg, current)
        if msg.sender_id != current.id:
            # 非管理员只能撤回自己的留言；删别人的活留给管理员
            raise Forbidden("只能撤回自己发送的留言")
        if (
            msg.created_at is None
            or datetime.now() - msg.created_at
            > timedelta(minutes=RECALL_WINDOW_MINUTES)
        ):
            raise BadRequest(
                f"超过 {RECALL_WINDOW_MINUTES} 分钟的留言不能撤回，可联系管理员处理"
            )

    msg.is_deleted = True
    msg.deleted_at = datetime.now().replace(microsecond=0)
    msg.deleted_by = current.id
    await db.commit()
    await db.refresh(msg)
    await _decorate(db, [msg], current)
    return msg


# ---------------------------------------------------------------------------
# 8.1.3 附件
# ---------------------------------------------------------------------------


async def save_attachment(
    db: AsyncSession,
    message_id: int,
    *,
    original_name: str,
    stored_path: str,
    file_size: int,
    mime_type: str | None,
    current: User,
) -> Attachment:
    """登记一张挂在留言上的附件（物理文件由路由层落盘）。"""
    msg = await _get_message_or_404(db, message_id)
    await _assert_participant(db, msg, current)
    if msg.is_deleted:
        raise BadRequest("该留言已撤回，无法继续上传附件")

    att = Attachment(
        biz_type="message",
        biz_id=msg.id,
        file_name=original_name,
        file_path=stored_path,
        file_size=file_size,
        mime_type=mime_type,
        uploader_id=current.id,
    )
    db.add(att)
    await db.commit()
    await db.refresh(att)
    return att


async def get_attachment(
    db: AsyncSession, attachment_id: int, current: User
) -> Attachment:
    """读取留言附件并校验会话参与方，供下载/预览。"""
    att = await db.get(Attachment, attachment_id)
    if att is None or att.biz_type != "message":
        raise NotFound("附件不存在")
    msg = await db.get(Message, att.biz_id)
    if msg is None:
        raise NotFound("附件所属留言已删除")
    await _assert_participant(db, msg, current)
    # 留言撤回后附件随之下线：否则「撤回」只是把文字藏了，文件还能直接下
    if msg.is_deleted and current.role != "admin":
        raise NotFound("留言已撤回，附件不可访问")
    return att


async def list_message_attachments(
    db: AsyncSession, message_id: int, current: User
) -> list[Attachment]:
    """某条留言的附件列表。"""
    msg = await _get_message_or_404(db, message_id)
    await _assert_participant(db, msg, current)
    if msg.is_deleted:
        return []
    rows = await db.execute(
        select(Attachment)
        .where(Attachment.biz_type == "message", Attachment.biz_id == message_id)
        .order_by(Attachment.id)
    )
    return list(rows.scalars().all())

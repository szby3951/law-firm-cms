"""客户端自助路由：我的案件、我的合同、我的账单、在线缴费、我的文书。

客户端只能通过本模块访问与自己相关的数据，行级隔离到本人。
"""

from fastapi import APIRouter, Query, Request
from fastapi.responses import FileResponse

from app.dependencies import CurrentUser, DbSession, client_ip
from app.schemas.billing import BillOut, PaymentOut
from app.schemas.case import (
    AttachmentOut,
    CaseDetailOut,
    CaseEventOut,
    CaseLawyerOut,
    CaseOut,
)
from app.schemas.contract import ContractOut
from app.schemas.document import DocumentItemOut, DocumentOut
from app.schemas.message import (
    MessageListOut,
    MessageReadOut,
    MessageUnreadOut,
)
from app.schemas.notification import (
    NotificationListOut,
    NotificationOut,
    NotificationReadAllOut,
    NotificationUnreadOut,
)
from app.schemas.payment import (
    PaymentOrderIn,
    PaymentOrderOut,
    PaymentOrderPayOut,
    SandboxPayIn,
)
from app.services import (
    audit_service,
    billing_service,
    case_service,
    contract_service,
    doc_service,
    message_service,
    notification_service,
    payment_service,
)

router = APIRouter()


@router.get("/cases", response_model=list[CaseOut], summary="我的案件列表")
async def my_cases(db: DbSession, user: CurrentUser) -> list[CaseOut]:
    """当前登录客户本人委托的案件列表。"""
    cases = await case_service.list_my_cases(db, user)
    return [CaseOut.model_validate(c) for c in cases]


@router.get("/cases/{case_id}", response_model=CaseDetailOut, summary="我的案件详情")
async def my_case_detail(
    case_id: int, db: DbSession, user: CurrentUser
) -> CaseDetailOut:
    """当前客户本人案件的详情（含时间线）。

    仅能访问 ``client_profile.user_id == 本人`` 的案件。
    """
    # 复用详情聚合，但需按客户身份做隔离校验
    case = await case_service.get_my_case(db, case_id, user)

    # 聚合承办律师（含姓名），客户端只读展示
    lawyer_rows = await case_service.list_case_lawyers(db, case_id)
    lawyers = [
        CaseLawyerOut(lawyer_id=rel.lawyer_id, duty=rel.duty, lawyer_name=name)
        for rel, name in lawyer_rows
    ]

    events = [
        CaseEventOut.model_validate(e)
        for e in await case_service.list_case_events(db, case_id)
    ]
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


@router.get("/contracts", response_model=list[ContractOut], summary="我的合同列表")
async def my_contracts(db: DbSession, user: CurrentUser) -> list[ContractOut]:
    """当前登录客户本人关联的合同列表（只读）。"""
    contracts = await contract_service.list_my_contracts(db, user)
    return [ContractOut.model_validate(c) for c in contracts]


@router.get("/contracts/{contract_id}", response_model=ContractOut, summary="我的合同详情")
async def my_contract_detail(
    contract_id: int, db: DbSession, user: CurrentUser
) -> ContractOut:
    """当前客户本人关联合同的详情（只读，行级隔离）。"""
    contract = await contract_service.get_my_contract(db, contract_id, user)
    return contract


@router.get("/bills", response_model=list[BillOut], summary="我的账单列表")
async def my_bills(db: DbSession, user: CurrentUser) -> list[BillOut]:
    """当前登录客户本人委托案件的账单：应收 / 已缴 / 状态 / 发票状态。"""
    return await billing_service.list_my_bills(db, user)


# ---------------------------------------------------------------------------
# 5.2 在线缴费（沙箱支付）
# ---------------------------------------------------------------------------


@router.post(
    "/bills/{period_id}/payment-orders",
    response_model=PaymentOrderOut,
    summary="发起在线缴费",
)
async def create_payment_order(
    period_id: int,
    payload: PaymentOrderIn,
    db: DbSession,
    user: CurrentUser,
) -> PaymentOrderOut:
    """为某一期账单创建支付订单（金额缺省为待缴全额，支持部分缴费）。"""
    order = await payment_service.create_order(db, period_id, payload, user)
    return PaymentOrderOut.model_validate(order)


@router.get(
    "/payment-orders/{order_no}",
    response_model=PaymentOrderOut,
    summary="查询支付订单",
)
async def get_payment_order(
    order_no: str, db: DbSession, user: CurrentUser
) -> PaymentOrderOut:
    """查询订单状态，供收银台轮询/刷新使用。"""
    order = await payment_service.get_order(db, order_no, user)
    return PaymentOrderOut.model_validate(order)


@router.post(
    "/payment-orders/{order_no}/sandbox-pay",
    response_model=PaymentOrderPayOut,
    summary="沙箱支付确认",
)
async def sandbox_pay(
    order_no: str,
    payload: SandboxPayIn,
    request: Request,
    db: DbSession,
    user: CurrentUser,
) -> PaymentOrderPayOut:
    """模拟第三方支付网关确认。

    成功：生成收款记录并联动期次状态（律师端/管理员端立即可见）；
    失败：仅把订单置为 failed，不产生收款记录。重复确认幂等。
    """
    order, payment, period = await payment_service.sandbox_pay(
        db, order_no, payload.result, payload.reason, user
    )
    if payment is not None:
        await audit_service.write_log_safe(
            db,
            user_id=user.id,
            action=audit_service.ACTION_CREATE,
            target=f"payment:{payment.id}",
            detail=(
                f"客户在线缴费 {payment.amount} 元"
                f"（{order.channel}，订单 {order.order_no}）"
            ),
            ip=client_ip(request),
        )

    return PaymentOrderPayOut(
        order=PaymentOrderOut.model_validate(order),
        payment=PaymentOut.model_validate(payment) if payment else None,
        period=billing_service.to_period_out(period) if period else None,
    )


@router.post(
    "/payment-orders/{order_no}/cancel",
    response_model=PaymentOrderOut,
    summary="取消支付订单",
)
async def cancel_payment_order(
    order_no: str, db: DbSession, user: CurrentUser
) -> PaymentOrderOut:
    """客户主动取消待支付订单。"""
    order = await payment_service.cancel_order(db, order_no, user)
    return PaymentOrderOut.model_validate(order)


# ---------------------------------------------------------------------------
# 6.1.7 客户端通知（仅开庭/期限等对外提醒）
# ---------------------------------------------------------------------------


@router.get(
    "/notifications", response_model=NotificationListOut, summary="我的通知列表"
)
async def my_notifications(
    db: DbSession,
    user: CurrentUser,
    is_read: bool | None = Query(default=None, description="是否已读"),
    page: int = Query(default=1, ge=1, description="页码"),
    page_size: int = Query(default=20, ge=1, le=100, description="每页数量"),
) -> NotificationListOut:
    """客户端通知：只包含与本人案件相关的开庭/期限/缴费/合同提醒。"""
    total, unread, items = await notification_service.list_client_notifications(
        db,
        current=user,
        is_read=is_read,
        page=page,
        page_size=page_size,
    )
    return NotificationListOut(
        total=total,
        unread=unread,
        items=[NotificationOut.model_validate(x) for x in items],
    )


@router.get(
    "/notifications/unread-count",
    response_model=NotificationUnreadOut,
    summary="未读通知数",
)
async def my_unread_count(
    db: DbSession, user: CurrentUser
) -> NotificationUnreadOut:
    """客户端红点：未读的对外通知数量。"""
    return NotificationUnreadOut(
        count=await notification_service.count_client_unread(db, user)
    )


@router.patch(
    "/notifications/read-all",
    response_model=NotificationReadAllOut,
    summary="全部标记已读",
)
async def my_read_all(
    db: DbSession, user: CurrentUser
) -> NotificationReadAllOut:
    """把本人全部通知置为已读。"""
    updated = await notification_service.mark_all_read(db, user.id)
    return NotificationReadAllOut(updated=updated)


@router.patch(
    "/notifications/{notification_id}/read",
    response_model=NotificationOut,
    summary="标记已读",
)
async def my_mark_read(
    notification_id: int, db: DbSession, user: CurrentUser
) -> NotificationOut:
    """标记本人的单条通知已读。"""
    notice = await notification_service.mark_read(db, notification_id, user.id)
    return NotificationOut.model_validate(notice)


# ---------------------------------------------------------------------------
# 8.1.5 客户端留言（与承办律师的双向沟通记录）
# ---------------------------------------------------------------------------


@router.get("/messages", response_model=MessageListOut, summary="我的留言")
async def my_messages(
    db: DbSession,
    user: CurrentUser,
    lawyer_id: int | None = Query(default=None, description="指定律师（默认全部）"),
    page: int = Query(default=1, ge=1, description="页码（1 = 最新一屏）"),
    page_size: int = Query(default=50, ge=1, le=100, description="每页数量"),
) -> MessageListOut:
    """当前客户与承办律师的沟通记录（双向，按时间正序）。"""
    return await message_service.list_messages(
        db,
        current=user,
        client_id=None,
        lawyer_id=lawyer_id,
        page=page,
        page_size=page_size,
    )


@router.get(
    "/messages/unread-count",
    response_model=MessageUnreadOut,
    summary="未读留言数",
)
async def my_messages_unread(
    db: DbSession, user: CurrentUser
) -> MessageUnreadOut:
    """客户端红点：律师回复中我还没看的条数。"""
    return MessageUnreadOut(count=await message_service.count_unread(db, user))


@router.patch(
    "/messages/read-all",
    response_model=MessageReadOut,
    summary="留言全部标记已读",
)
async def my_messages_read_all(
    db: DbSession, user: CurrentUser
) -> MessageReadOut:
    """把律师发来的未读留言全部置为已读。"""
    return MessageReadOut(updated=await message_service.mark_all_read(db, user))


# ---------------------------------------------------------------------------
# 7.1.6 客户端文书（仅已发布，行级隔离到本人案件）
# ---------------------------------------------------------------------------

DOCX_MEDIA_TYPE = (
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
)


@router.get(
    "/documents", response_model=list[DocumentItemOut], summary="我的文书列表"
)
async def my_documents(
    db: DbSession,
    user: CurrentUser,
    doc_type: str | None = Query(default=None, description="文书类型"),
    keyword: str | None = Query(default=None, description="标题关键词"),
) -> list[DocumentItemOut]:
    """当前客户本人案件下、律师已发布的文书（不含未发布草稿）。"""
    docs = await doc_service.list_my_documents(
        db, current=user, doc_type=doc_type, keyword=keyword
    )
    return [DocumentItemOut.model_validate(d) for d in docs]


@router.get(
    "/documents/{document_id}",
    response_model=DocumentOut,
    summary="我的文书详情",
)
async def my_document_detail(
    document_id: int, db: DbSession, user: CurrentUser
) -> DocumentOut:
    """查看本人案件的已发布文书正文（在线预览）。"""
    doc = await doc_service.get_document(db, document_id, user)
    return DocumentOut.model_validate(doc)


@router.get("/documents/{document_id}/download", summary="下载我的文书")
async def my_document_download(
    document_id: int, request: Request, db: DbSession, user: CurrentUser
) -> FileResponse:
    """下载文书 docx；律师尚未导出时此处会即时生成一份。"""
    abs_path, file_name = await doc_service.get_download(db, document_id, user)
    await audit_service.write_log_safe(
        db,
        user_id=user.id,
        action=audit_service.ACTION_EXPORT,
        target=f"document:{document_id}",
        detail=f"客户下载文书 #{document_id}（{file_name}）",
        ip=client_ip(request),
    )
    return FileResponse(
        path=abs_path,
        media_type=DOCX_MEDIA_TYPE,
        filename=file_name,
    )

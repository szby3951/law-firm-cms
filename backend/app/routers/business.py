"""「AI督办」路由：读本人案件、费用、日程、合同的问答入口。

和 ``/api/ai`` 分开注册是有意的。两个入口的用户意图不同、数据来源不同、
合规口径也不同，共用前缀会让人以为「换了个 prompt 而已」：

====================  ==========================  ============================
                      ``/api/ai``（法律问答）      ``/api/business``（AI督办）
====================  ==========================  ============================
数据来源              ``law_kb`` 向量库           业务表（cases / billing / …）
回答依据              法条，逐条标 ``[n]``       台账数字，逐字照抄
不做的事              查案件进度与欠费            解释法条、评估胜诉
会话类型              ``ai_session.type='chat'``  ``ai_session.type='business'``
====================  ==========================  ============================

会话的读取与删除仍走 ``/api/ai/sessions``（带 ``type=business`` 过滤）——那边
的按 ``user_id`` 隔离逻辑本来就与类型无关，没必要复制一份。
"""

import logging

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from app.dependencies import CurrentUser, DbSession
from app.schemas.ai import BusinessChatIn
from app.services import business_chat_service

router = APIRouter()
logger = logging.getLogger(__name__)

_SSE_HEADERS = {
    "Cache-Control": "no-cache, no-transform",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}


@router.post("/chat", summary="AI督办问答（SSE 流式）")
async def business_chat(
    db: DbSession, user: CurrentUser, payload: BusinessChatIn, request: Request
) -> StreamingResponse:
    """读业务台账 → 拼提示词 → 流式生成 → 落库。

    对全部登录用户开放：客户查本人委托的案件与费用，律师查本人承办案件、待收款
    与日程，管理员看全所口径。范围由 ``personal_context_service`` 复用既有
    service 决定，与页面看到的一致。

    事件类型见 :mod:`app.services.business_chat_service` 顶部说明。没有 ``refs``
    事件——这一侧不检索法条。
    """
    plan = await business_chat_service.prepare_business_chat(db, user, payload)
    logger.info(
        "业务问答请求 | user=%s(%s) | session=%s | 数据 %d 字 | %s",
        user.username,
        user.role,
        plan.session_id,
        len(plan.context_text),
        request.client.host if request.client else "-",
    )
    return StreamingResponse(
        business_chat_service.stream_business_reply(plan),
        media_type="text/event-stream",
        headers=_SSE_HEADERS,
    )

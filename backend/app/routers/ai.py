"""AI 法律助手路由（任务拆解 9.3.6 / 9.4.3 / 9.5.4 / 9.6.2）。

``/api/ai`` 下的接口：

**问答**
- ``POST /chat``  RAG 问答，``text/event-stream`` 流式返回

**会话管理（9.3.5）**
- ``GET    /sessions``          我的会话列表
- ``POST   /sessions``          新建空会话
- ``GET    /sessions/{id}``     会话详情（含全部消息与引用快照）
- ``PATCH  /sessions/{id}``     重命名
- ``DELETE /sessions/{id}``     删除（消息级联删除）

**文书生成（9.4）**
- ``GET  /document-types``      可生成的文书类型、必备字段与结构
- ``POST /generate-document``   生成初稿，SSE 流式返回
- ``POST /documents``           把初稿（可经律师修改）归档进文书库

**合同风险审查（9.5）**
- ``POST /review-contract/{id}`` 读取合同文件或粘贴稿，分批评审后写回
  ``contract.ai_review_report``，SSE 逐批回报进度

**案件摘要（9.6）**
- ``POST /case-summary/{case_id}`` 聚合案件档案与卷宗材料，SSE 流式输出摘要
- ``GET  /case-summary/{case_id}`` 读取本人最近一次生成的摘要

**运维**
- ``GET /health``               模型 + 向量服务 + 知识库配置快照

权限：问答对所有登录用户开放（客户端也要用，见 9.8.6）；健康检查与文书生成
只给律师/管理员——客户账号不开放文书生成（架构文档 5.8）。案件摘要同样只给
律师/管理员，且必须是该案承办律师（管理员不限）。会话一律按 ``user_id`` 隔离，
管理员也不能查看他人的咨询记录。

关于流式响应与数据库会话：``/chat``、``/generate-document`` 里**不使用**请求级
``DbSession`` 去写助手消息。FastAPI 的 ``yield`` 依赖在响应开始后就会被清理，
而生成器要跑到最后一段文本才结束，用同一个会话会踩到"连接已关闭"。写入由
:class:`app.services.ai_service._AssistantSink` 自己开短会话完成。
"""

import logging
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import StreamingResponse

from app.ai import doc_prompts, prompts
from app.ai.gateway import get_gateway
from app.config import settings
from app.dependencies import CurrentUser, DbSession, client_ip, require_role
from app.models.user import User
from app.schemas.ai import (
    AiCaseSummaryIn,
    AiCaseSummaryOut,
    AiChatIn,
    AiContractReviewIn,
    AiDocArchiveIn,
    AiDocGenerateIn,
    AiDocTypeOut,
    AiSessionCreate,
    AiSessionDetailOut,
    AiSessionListOut,
    AiSessionOut,
    AiSessionUpdate,
)
from app.schemas.document import DocumentOut
from app.services import ai_service, audit_service

router = APIRouter()
logger = logging.getLogger(__name__)

StaffUser = Annotated[User, Depends(require_role("lawyer", "admin"))]

# SSE 必须关掉各级缓冲，否则 Nginx/浏览器会把分段攒成一整块，流式就白做了
_SSE_HEADERS = {
    "Cache-Control": "no-cache, no-transform",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}


@router.post("/chat", summary="RAG 问答（SSE 流式）")
async def chat(
    db: DbSession, user: CurrentUser, payload: AiChatIn, request: Request
) -> StreamingResponse:
    """检索法条 → 拼提示词 → 流式生成 → 落库。

    这里只回答**法律知识**问题：法条怎么规定、程序怎么走、这类情形一般怎么处理。
    问「我的案子办到哪了」「我还差多少钱」请走 ``/api/business/chat``——那条链路
    读的是业务台账，不检索法条，两边的会话也不互通。

    事件类型见 :mod:`app.services.ai_service` 顶部说明。前端用
    ``fetch`` + ``ReadableStream`` 读取（需要带 Authorization 头，不能用
    ``EventSource``）。
    """
    plan = await ai_service.prepare_chat(db, user, payload)
    logger.info(
        "法律问答请求 | user=%s(%s) | session=%s | %s",
        user.username,
        user.role,
        plan.session_id,
        request.client.host if request.client else "-",
    )
    return StreamingResponse(
        ai_service.stream_reply(plan),
        media_type="text/event-stream",
        headers=_SSE_HEADERS,
    )


@router.get(
    "/document-types",
    response_model=list[AiDocTypeOut],
    summary="可生成的文书类型与格式要求",
)
async def list_document_types(user: StaffUser) -> list[AiDocTypeOut]:
    """供前端「选类型」步骤展示：需要哪些案件字段、必须包含哪些章节。

    把格式规范暴露出来不是为了给前端抄一遍，而是为了让律师在建文书前就看到
    「受理法院、对方当事人还没填」——比生成完再发现一堆占位符要省事。
    """
    return [
        AiDocTypeOut(
            doc_type=key,
            label=spec.label,
            required_fields=list(spec.fields),
            outline=list(spec.outline),
            rules=list(spec.rules),
        )
        for key, spec in doc_prompts.DOC_SPECS.items()
    ]


@router.post("/generate-document", summary="AI 生成文书初稿（SSE 流式）")
async def generate_document(
    db: DbSession,
    user: StaffUser,
    payload: AiDocGenerateIn,
    request: Request,
) -> StreamingResponse:
    """选类型 + 带案件字段 → 流式生成初稿。

    生成结果不直接入库：``done`` 事件里带 ``content``（Markdown）与 ``html``，
    律师在编辑器里改完后调用 ``POST /api/ai/documents`` 归档。
    """
    plan = await ai_service.prepare_document(db, user, payload)
    logger.info(
        "文书生成请求 | user=%s(%s) | %s | case=%s | session=%s | %s",
        user.username,
        user.role,
        plan.label,
        plan.case_id,
        plan.session_id,
        request.client.host if request.client else "-",
    )
    return StreamingResponse(
        ai_service.stream_document(plan),
        media_type="text/event-stream",
        headers=_SSE_HEADERS,
    )


@router.post(
    "/documents",
    response_model=DocumentOut,
    status_code=201,
    summary="归档 AI 文书到文书库",
)
async def archive_document(
    payload: AiDocArchiveIn,
    request: Request,
    db: DbSession,
    user: StaffUser,
) -> DocumentOut:
    """把初稿正文存为 ``document`` 记录，``is_ai_generated=true`` 并记录来源会话。"""
    doc = await ai_service.archive_document(db, user, payload)
    await audit_service.write_log_safe(
        db,
        user_id=user.id,
        action=audit_service.ACTION_CREATE,
        target=f"document:{doc.id}",
        detail=f"归档 AI 生成文书「{doc.title}」",
        ip=client_ip(request),
    )
    return DocumentOut.model_validate(doc)


@router.post(
    "/review-contract/{contract_id}",
    summary="AI 合同风险审查（SSE 流式进度）",
)
async def review_contract(
    contract_id: int,
    request: Request,
    db: DbSession,
    user: StaffUser,
    payload: AiContractReviewIn | None = None,
) -> StreamingResponse:
    """读取合同文件（或律师粘贴的正文）→ 切分条款 → 分批评审 → 写回合同台账。

    请求体可省略：不传 ``text`` 时自动读取台账里已上传的文件。

    这里**不**在响应前做任何模型调用：权限、文件、文本长度问题都在
    ``prepare_review`` 里以 403/404/400 返回，SSE 一旦开始就只能用 ``error`` 事件
    表达失败。
    """
    plan = await ai_service.prepare_review(
        db, user, contract_id, payload or AiContractReviewIn()
    )
    logger.info(
        "合同审查请求 | user=%s(%s) | contract=%s | %d 批 | %s",
        user.username,
        user.role,
        plan.contract_id,
        len(plan.batches),
        request.client.host if request.client else "-",
    )
    return StreamingResponse(
        ai_service.stream_review(plan),
        media_type="text/event-stream",
        headers=_SSE_HEADERS,
    )


@router.post(
    "/case-summary/{case_id}",
    summary="AI 案件摘要（SSE 流式）",
)
async def case_summary(
    case_id: int,
    request: Request,
    db: DbSession,
    user: StaffUser,
    payload: AiCaseSummaryIn | None = None,
) -> StreamingResponse:
    """聚合案件档案、时间线、日程、文书、合同与附件 → 六段式摘要。

    请求体可省略；默认读取案卷材料。传 ``include_materials=false`` 只依据
    案件档案与时间线，用于材料尚未整理完、先出一份框架摘要的场景。

    权限在 ``prepare_case_summary`` 内校验（仅承办律师/管理员），失败时以
    403/404 在流开始前返回；SSE 一旦开始，失败只能通过 ``error`` 事件表达。
    """
    plan = await ai_service.prepare_case_summary(
        db, user, case_id, payload or AiCaseSummaryIn()
    )
    logger.info(
        "案件摘要请求 | user=%s(%s) | case=%s | 材料 %d 份 | %s",
        user.username,
        user.role,
        plan.case_id,
        plan.bundle.material_count,
        request.client.host if request.client else "-",
    )
    return StreamingResponse(
        ai_service.stream_case_summary(plan),
        media_type="text/event-stream",
        headers=_SSE_HEADERS,
    )


@router.get(
    "/case-summary/{case_id}",
    response_model=AiCaseSummaryOut,
    summary="读取最近一次案件摘要",
)
async def get_case_summary(
    case_id: int, db: DbSession, user: StaffUser
) -> AiCaseSummaryOut:
    """供前端进入案件详情时回填上次结果；没有生成过时 ``content`` 为空。"""
    return await ai_service.get_latest_summary(db, user, case_id)


@router.get("/health", summary="AI 服务健康检查")
async def ai_health(user: StaffUser) -> dict:
    """大模型、向量服务与知识库配置的一次性快照，用于排查"为什么答不出来"。"""
    data = await get_gateway().health()
    data["rag"] = {
        "top_k": settings.rag_top_k,
        "min_score": settings.rag_min_score,
        "collection": settings.qdrant_collection,
        "max_context_chars": settings.rag_max_context_chars,
        "history_messages": settings.ai_history_messages,
    }
    data["disclaimer"] = prompts.DISCLAIMER
    return data


@router.get("/sessions", response_model=AiSessionListOut, summary="我的会话列表")
async def list_sessions(
    db: DbSession,
    user: CurrentUser,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    type: str | None = Query(
        default=None,
        description="按类型过滤：chat 法律问答 / business AI督办；不传返回全部",
    ),
) -> AiSessionListOut:
    total, items = await ai_service.list_sessions(
        db, user, page=page, page_size=page_size, session_type=type
    )
    return AiSessionListOut(total=total, items=items)


@router.post(
    "/sessions",
    response_model=AiSessionOut,
    status_code=201,
    summary="新建会话",
)
async def create_session(
    db: DbSession, user: CurrentUser, payload: AiSessionCreate
) -> AiSessionOut:
    return await ai_service.create_session(db, user, payload)


@router.get(
    "/sessions/{session_id}",
    response_model=AiSessionDetailOut,
    summary="会话详情（历史消息）",
)
async def get_session(
    db: DbSession,
    user: CurrentUser,
    session_id: int,
    session_type: Literal["chat", "business"] | None = Query(
        default=None,
        alias="type",
        description=(
            "按入口校验会话归属：chat=法律问答、business=AI督办。"
            "传了但不匹配返回 404，防止另一端的历史消息串进来"
        ),
    ),
) -> AiSessionDetailOut:
    return await ai_service.get_session(db, user, session_id, session_type=session_type)


@router.patch(
    "/sessions/{session_id}", response_model=AiSessionOut, summary="重命名会话"
)
async def rename_session(
    db: DbSession, user: CurrentUser, session_id: int, payload: AiSessionUpdate
) -> AiSessionOut:
    return await ai_service.rename_session(db, user, session_id, payload)


@router.delete("/sessions/{session_id}", status_code=204, summary="删除会话")
async def delete_session(db: DbSession, user: CurrentUser, session_id: int) -> None:
    await ai_service.delete_session(db, user, session_id)

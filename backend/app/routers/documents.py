"""文书管理路由：文书 CRUD、模板生成草稿、docx 导出/下载、模板 CRUD。

权限：本路由面向律师与管理员；客户走 ``/api/my/documents``（见 ``my.py``）。
"""

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import FileResponse

from app.dependencies import CurrentUser, DbSession, client_ip, require_role
from app.models.user import User
from app.schemas.document import (
    TEMPLATE_VARIABLES,
    DocumentExportOut,
    DocumentFromTemplateIn,
    DocumentIn,
    DocumentListOut,
    DocumentOut,
    GeneratedDocOut,
    TemplateBriefOut,
    TemplateIn,
    TemplateListOut,
    TemplateOut,
)
from app.services import audit_service, doc_service

router = APIRouter()
# 模板接口挂在 /api/doc-templates 下，与文书接口共用同一模块
template_router = APIRouter()

LawyerOrAdmin = Annotated[User, Depends(require_role("lawyer", "admin"))]

DOCX_MEDIA_TYPE = (
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
)


# ---------------------------------------------------------------------------
# 文书
# ---------------------------------------------------------------------------


@router.get("", response_model=DocumentListOut, summary="文书列表（分页）")
async def list_documents(
    db: DbSession,
    user: LawyerOrAdmin,
    case_id: int | None = Query(default=None, description="关联案件ID"),
    doc_type: str | None = Query(default=None, description="文书类型"),
    status: str | None = Query(default=None, description="状态"),
    keyword: str | None = Query(default=None, description="标题关键词"),
    created_by: int | None = Query(default=None, description="创建人ID"),
    page: int = Query(default=1, ge=1, description="页码"),
    page_size: int = Query(default=20, ge=1, le=100, description="每页数量"),
) -> DocumentListOut:
    """分页查询文书，律师仅见本人或本人承办案件下的文书。"""
    total, items = await doc_service.list_documents(
        db,
        current=user,
        case_id=case_id,
        doc_type=doc_type,
        status=status,
        keyword=keyword,
        created_by=created_by,
        page=page,
        page_size=page_size,
    )
    return DocumentListOut(total=total, items=items)


@router.post("", response_model=DocumentOut, summary="新建文书")
async def create_document(
    payload: DocumentIn,
    request: Request,
    db: DbSession,
    user: LawyerOrAdmin,
) -> DocumentOut:
    """新建文书；关联案件时自动带出委托客户。"""
    doc = await doc_service.create_document(db, payload, user)
    await audit_service.write_log_safe(
        db,
        user_id=user.id,
        action=audit_service.ACTION_CREATE,
        target=f"document:{doc.id}",
        detail=f"新建文书「{doc.title}」",
        ip=client_ip(request),
    )
    return DocumentOut.model_validate(doc)


@router.post(
    "/generate",
    response_model=GeneratedDocOut,
    summary="按模板生成文书草稿",
)
async def generate_document(
    payload: DocumentFromTemplateIn,
    db: DbSession,
    user: LawyerOrAdmin,
) -> GeneratedDocOut:
    """选择模板 + 案件，自动填充 {客户姓名}{案号} 等变量后返回草稿。

    仅返回填充结果不落库，前端在编辑器中确认后再调用新建接口保存。
    """
    return await doc_service.generate_from_template(db, payload, user)


@router.get("/{document_id}", response_model=DocumentOut, summary="文书详情")
async def get_document(
    document_id: int, db: DbSession, user: CurrentUser
) -> DocumentOut:
    """文书详情（含富文本正文）。"""
    doc = await doc_service.get_document(db, document_id, user)
    return DocumentOut.model_validate(doc)


@router.put("/{document_id}", response_model=DocumentOut, summary="修改文书")
async def update_document(
    document_id: int,
    payload: DocumentIn,
    request: Request,
    db: DbSession,
    user: LawyerOrAdmin,
) -> DocumentOut:
    """全量更新文书（草稿保存 / 定稿 / 发布给客户）。"""
    doc = await doc_service.update_document(db, document_id, payload, user)
    await audit_service.write_log_safe(
        db,
        user_id=user.id,
        action=audit_service.ACTION_UPDATE,
        target=f"document:{doc.id}",
        detail=f"修改文书「{doc.title}」→ {doc.status}",
        ip=client_ip(request),
    )
    return DocumentOut.model_validate(doc)


@router.delete("/{document_id}", status_code=204, summary="删除文书")
async def delete_document(
    document_id: int, request: Request, db: DbSession, user: LawyerOrAdmin
) -> None:
    """删除文书及其导出的 docx 文件。"""
    await doc_service.delete_document(db, document_id, user)
    await audit_service.write_log_safe(
        db,
        user_id=user.id,
        action=audit_service.ACTION_DELETE,
        target=f"document:{document_id}",
        detail=f"删除文书 #{document_id}",
        ip=client_ip(request),
    )


@router.post(
    "/{document_id}/export",
    response_model=DocumentExportOut,
    summary="导出 docx",
)
async def export_document(
    document_id: int,
    request: Request,
    db: DbSession,
    user: CurrentUser,
) -> DocumentExportOut:
    """把文书渲染成 docx 落盘，返回下载地址（可重复导出，覆盖旧文件）。"""
    doc, _abs_path, file_name, size = await doc_service.export_document(
        db, document_id, user
    )
    await audit_service.write_log_safe(
        db,
        user_id=user.id,
        action=audit_service.ACTION_EXPORT,
        target=f"document:{doc.id}",
        detail=f"导出文书「{doc.title}」为 docx",
        ip=client_ip(request),
    )
    return DocumentExportOut(
        document_id=doc.id,
        file_name=file_name,
        file_url=doc.file_url or "",
        download_url=f"/api/documents/{doc.id}/download",
        file_size=size,
        exported_at=datetime.now(),
    )


@router.get("/{document_id}/download", summary="下载 docx")
async def download_document(
    document_id: int, db: DbSession, user: CurrentUser
) -> FileResponse:
    """下载文书 docx（未导出时自动生成，客户仅能下载已发布文书）。"""
    abs_path, file_name = await doc_service.get_download(db, document_id, user)
    return FileResponse(
        path=abs_path,
        media_type=DOCX_MEDIA_TYPE,
        filename=file_name,
    )


# ---------------------------------------------------------------------------
# 模板
# ---------------------------------------------------------------------------


@template_router.get("/variables", summary="模板可用变量清单")
async def list_variables(user: LawyerOrAdmin) -> list[dict[str, str]]:
    """返回模板支持的全部占位符，供前端「插入变量」下拉使用。"""
    return list(TEMPLATE_VARIABLES)


@template_router.get("", response_model=TemplateListOut, summary="模板列表")
async def list_templates(
    db: DbSession,
    user: LawyerOrAdmin,
    doc_type: str | None = Query(default=None, description="文书类型"),
    keyword: str | None = Query(default=None, description="名称关键词"),
    page: int = Query(default=1, ge=1, description="页码"),
    page_size: int = Query(default=100, ge=1, le=200, description="每页数量"),
) -> TemplateListOut:
    """模板库列表（全所共享），附变量清单与正文摘要。"""
    total, items = await doc_service.list_templates(
        db,
        doc_type=doc_type,
        keyword=keyword,
        page=page,
        page_size=page_size,
    )
    return TemplateListOut(
        total=total, items=[TemplateBriefOut.model_validate(x) for x in items]
    )


@template_router.post("", response_model=TemplateOut, summary="新建模板")
async def create_template(
    payload: TemplateIn,
    request: Request,
    db: DbSession,
    user: LawyerOrAdmin,
) -> TemplateOut:
    """新建文书模板（正文可含 {客户姓名} 等占位符）。"""
    template = await doc_service.create_template(db, payload, user)
    await audit_service.write_log_safe(
        db,
        user_id=user.id,
        action=audit_service.ACTION_CREATE,
        target=f"doc_template:{template.id}",
        detail=f"新建文书模板「{template.name}」",
        ip=client_ip(request),
    )
    return TemplateOut.model_validate(template)


@template_router.get(
    "/{template_id}", response_model=TemplateOut, summary="模板详情"
)
async def get_template(
    template_id: int, db: DbSession, user: LawyerOrAdmin
) -> TemplateOut:
    """模板详情（含完整正文）。"""
    template = await doc_service.get_template(db, template_id)
    return TemplateOut.model_validate(template)


@template_router.put(
    "/{template_id}", response_model=TemplateOut, summary="修改模板"
)
async def update_template(
    template_id: int,
    payload: TemplateIn,
    request: Request,
    db: DbSession,
    user: LawyerOrAdmin,
) -> TemplateOut:
    """全量更新模板。"""
    template = await doc_service.update_template(db, template_id, payload, user)
    await audit_service.write_log_safe(
        db,
        user_id=user.id,
        action=audit_service.ACTION_UPDATE,
        target=f"doc_template:{template.id}",
        detail=f"修改文书模板「{template.name}」",
        ip=client_ip(request),
    )
    return TemplateOut.model_validate(template)


@template_router.delete("/{template_id}", status_code=204, summary="删除模板")
async def delete_template(
    template_id: int, request: Request, db: DbSession, user: LawyerOrAdmin
) -> None:
    """删除模板（已生成的文书不受影响）。"""
    await doc_service.delete_template(db, template_id, user)
    await audit_service.write_log_safe(
        db,
        user_id=user.id,
        action=audit_service.ACTION_DELETE,
        target=f"doc_template:{template_id}",
        detail=f"删除文书模板 #{template_id}",
        ip=client_ip(request),
    )

"""路由聚合层。

各业务模块的路由在此登记，统一挂载到 ``settings.api_prefix``（/api）下。
新增模块时只需放开对应的 import + include 两行。
"""

from fastapi import APIRouter

from app.routers import (
    admin,
    ai,
    auth,
    billing,
    business,
    cases,
    clients,
    contracts,
    dicts,
    documents,
    kb,
    messages,
    my,
    notifications,
    schedule,
    settings,
    stats,
)

api_router = APIRouter()

# ---- 模块1 认证与权限 ----
api_router.include_router(auth.router, prefix="/auth")

# ---- 模块2 客户关系 ----
api_router.include_router(clients.router, prefix="/clients", tags=["客户管理"])

# ---- 模块3 案件管理 ----
api_router.include_router(cases.router, prefix="/cases", tags=["案件管理"])

# ---- 模块4 合同管理 ----
api_router.include_router(contracts.router, prefix="/contracts", tags=["合同管理"])

# ---- 模块5 收费管理 ----
api_router.include_router(billing.router, prefix="/billing", tags=["收费管理"])

# ---- 模块6 日程与通知 ----
api_router.include_router(schedule.router, prefix="/schedule", tags=["日程管理"])
api_router.include_router(
    notifications.router, prefix="/notifications", tags=["站内通知"]
)

# ---- 模块7 文书管理 ----
api_router.include_router(documents.router, prefix="/documents", tags=["文书管理"])
api_router.include_router(
    documents.template_router, prefix="/doc-templates", tags=["文书模板"]
)

# ---- 模块8 沟通留言 ----
api_router.include_router(messages.router, prefix="/messages", tags=["沟通留言"])

# ---- 模块9 AI 法律助手（9.1 知识库构建）----
api_router.include_router(kb.router, prefix="/admin/kb", tags=["知识库管理"])

# ---- 模块9 AI 法律助手（9.3 RAG 问答）----
api_router.include_router(ai.router, prefix="/ai", tags=["AI 法律助手"])

# ---- 模块9 AI督办（9.11 业务台账问答，与法律问答分链路）----
api_router.include_router(business.router, prefix="/business", tags=["AI督办"])

# ---- 客户端自助（我的案件/合同/账单/文书/通知）----
api_router.include_router(my.router, prefix="/my", tags=["客户端自助"])

# ---- 模块10 统计报表（管理员大屏 / 律师个人工作台）----
api_router.include_router(stats.router, prefix="/stats", tags=["统计报表"])

# ---- 模块11 系统管理（账号管理 / 操作日志）----
api_router.include_router(admin.router, prefix="/admin", tags=["系统管理"])

# ---- 模块11 系统设置（字典 / 律所信息 / AI 配置）----
api_router.include_router(settings.router, prefix="/admin", tags=["系统设置"])

# ---- 模块11 业务端只读字典（表单下拉候选）----
api_router.include_router(dicts.router, prefix="/dicts", tags=["数据字典"])

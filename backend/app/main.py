"""FastAPI 应用入口：实例化、CORS、路由注册、健康检查、生命周期管理。"""

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.ai.embedding import EmbeddingError
from app.ai.llm_clients.base import LLMError
from app.config import settings
from app.core.exceptions import AppError, app_error_handler
from app.core.logging import get_logger, setup_logging
from app.database import dispose_engine, engine
from app.routers import api_router
from app.scheduler import shutdown_scheduler, start_scheduler

setup_logging()
logger = get_logger(__name__)

# 生产环境关闭接口文档：/docs、/redoc 与 openapi.json 会把全部接口、参数与
# 字段结构交给任何能访问站点的人，属于免费的侦察材料。开发环境保持开启，
# 本地联调与接口核对（导出 openapi 清单）都不受影响。
DOCS_ENABLED = settings.app_env != "prod"


def _log_outbound_proxy() -> None:
    """打印出站代理状态，并提示被忽略的环境变量。

    排查「模型调用突然连不上」时，最先要看的就是这里：如果日志写着
    「直连」但进程环境里有 HTTP_PROXY，说明代理已被有意忽略——问题不在代理。
    """
    from app.ai.http_client import describe_proxy, ignored_env_proxies

    env_proxies = ignored_env_proxies()
    if settings.outbound_proxy.strip():
        logger.info("出站代理 | %s", describe_proxy())
        return
    if env_proxies:
        keys = "、".join(sorted(env_proxies))
        logger.warning(
            "检测到代理环境变量（%s），已忽略 | 出站为直连；"
            "如需走代理请在 .env 配置 OUTBOUND_PROXY",
            keys,
        )
    else:
        logger.info("出站代理 | 直连")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用启动/关闭钩子。"""
    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    logger.info(
        "应用启动 | env=%s | llm_enabled=%s | model=%s",
        settings.app_env,
        settings.llm_enabled,
        settings.llm_model,
    )
    _log_outbound_proxy()
    # 数据库里的 AI 配置（status=1 时）优先于 .env，启动时应用一次；
    # 读库失败不阻断启动——主系统必须在模型不可用时照常工作。
    try:
        from app.database import SessionLocal
        from app.services import dict_cache, setting_service

        async with SessionLocal() as db:
            source = await setting_service.load_ai_config(db)
            count = await dict_cache.refresh(db)
        logger.info("AI 配置来源 | %s | model=%s", source, settings.llm_model)
        logger.info("字典缓存已加载 | %s 条", count)
    except Exception as exc:  # noqa: BLE001  启动期读配置失败只告警
        logger.warning("读取数据库设置失败，沿用 .env 与内置标签 | %s", exc)

    # 提醒扫描定时任务：启动时注册（开庭/缴费/跟进/合同到期）
    start_scheduler()
    yield
    shutdown_scheduler()
    await dispose_engine()
    logger.info("应用已关闭，数据库连接池已释放")


app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    description="基于 LLM 的律所客户智能管理系统后端服务",
    lifespan=lifespan,
    docs_url="/docs" if DOCS_ENABLED else None,
    redoc_url="/redoc" if DOCS_ENABLED else None,
    openapi_url=f"{settings.api_prefix}/openapi.json" if DOCS_ENABLED else None,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router, prefix=settings.api_prefix)

# 业务异常统一转成 {"detail": "..."}，与前端 axios 拦截器约定一致
app.add_exception_handler(AppError, app_error_handler)


@app.exception_handler(LLMError)
async def llm_error_handler(request: Request, exc: LLMError) -> JSONResponse:
    """大模型不可用时降级为 503（任务拆解 9.2.4 / 9.9.4）。

    未配置 Key、上游限流、超时、连接失败都走这里：调用方（接口层）不需要
    逐个 try/except，也不会把 base_url、状态码等内部细节暴露给前端。
    真正的诊断信息写日志，响应只给一句可读提示。
    """
    logger.warning("大模型调用失败：%s（%s）", exc, request.url.path)
    return JSONResponse(
        status_code=503,
        content={"detail": exc.friendly},
    )


@app.exception_handler(EmbeddingError)
async def embedding_error_handler(
    request: Request, exc: EmbeddingError
) -> JSONResponse:
    """向量服务不可用时降级为 503（任务拆解 9.9.4）。

    知识库检索依赖向量化服务（云端接口或本地 TEI），它挂掉或超时
    不应让主系统看到 500；
    返回可读提示，前端按普通接口错误展示即可。
    """
    logger.warning("向量服务不可用：%s（%s）", exc, request.url.path)
    return JSONResponse(
        status_code=503,
        content={"detail": "AI 服务暂时不可用，请稍后重试"},
    )


@app.exception_handler(RequestValidationError)
async def validation_error_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    """把 pydantic 校验错误转成人类可读的中文提示，避免前端拿到一堆原始 JSON。"""
    messages = []
    for err in exc.errors():
        loc = err.get("loc", ())
        # loc 形如 ("body", "amount") 或 ("body", "client_id")，取最后一个字段名
        field = loc[-1] if loc else ""
        field = str(field)
        msg = err.get("msg", "")

        if err.get("type") == "value_error":
            # 自定义 field_validator 抛出的 ValueError，直接取原始中文提示
            # pydantic v2 会包一层 "Value error, " 前缀，这里统一剥掉
            messages.append(str(msg).removeprefix("Value error, "))
        elif err.get("type") in ("string_too_short", "string_too_long"):
            messages.append(f"字段「{field}」长度不合法：{msg}")
        elif err.get("type") == "missing":
            messages.append(f"缺少必填字段：{field}")
        elif err.get("type") == "decimal_parsing":
            messages.append(f"字段「{field}」不是合法的数字")
        elif err.get("type") == "int_parsing":
            messages.append(f"字段「{field}」不是合法的整数")
        elif err.get("type") == "greater_than_equal":
            messages.append(f"字段「{field}」不能小于限定值")
        elif err.get("type") == "less_than_equal":
            messages.append(f"字段「{field}」超出允许的最大值")
        elif err.get("type") == "string_pattern_mismatch":
            messages.append(f"字段「{field}」取值不在允许范围内")
        else:
            messages.append(f"字段「{field}」校验失败：{msg}")

    detail = "；".join(messages) if messages else "请求参数校验失败"
    return JSONResponse(status_code=422, content={"detail": detail})


@app.get("/", tags=["系统"], summary="服务信息")
async def root() -> dict[str, str]:
    """根路径：给出服务基本信息与入口链接，避免直接访问时返回 404。"""
    payload = {
        "name": settings.app_name,
        "version": app.version,
        "env": settings.app_env,
        "health": "/health",
    }
    if DOCS_ENABLED:
        payload["docs"] = "/docs"
        payload["openapi"] = f"{settings.api_prefix}/openapi.json"
    return payload


@app.get("/health", tags=["系统"], summary="健康检查")
async def health() -> dict:
    return {
        "status": "ok",
        "app": settings.app_name,
        "env": settings.app_env,
        "version": app.version,
    }


@app.get("/health/db", tags=["系统"], summary="数据库连通性检查")
async def health_db():
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
    except Exception as exc:  # noqa: BLE001  故意兜住全部异常，用于健康检查降级
        logger.warning("数据库连通性检查失败: %s", exc)
        # 开发环境保留首行原因（排查连接串/账号问题最直接）；
        # 生产只回一句泛化提示，避免把主机名、账号、驱动堆栈泄露给外部。
        detail = str(exc).splitlines()[0][:200] if settings.is_dev else "数据库不可用"
        return JSONResponse(
            status_code=503,
            content={
                "status": "error",
                "database": "unavailable",
                "detail": detail,
            },
        )
    return {"status": "ok", "database": "connected"}

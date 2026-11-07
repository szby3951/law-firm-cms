"""操作审计：登录、注册、删除、导出等敏感操作统一在此落库。"""

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.log import OperationLog

# 常用动作常量，避免各处硬编码字符串拼写不一致
ACTION_LOGIN = "login"
ACTION_LOGOUT = "logout"
ACTION_REGISTER = "register"
ACTION_CREATE = "create"
ACTION_UPDATE = "update"
ACTION_DELETE = "delete"
ACTION_EXPORT = "export"
ACTION_AI_CHAT = "ai_chat"


async def write_log(
    db: AsyncSession,
    *,
    user_id: int | None,
    action: str,
    target: str | None = None,
    detail: str | None = None,
    ip: str | None = None,
) -> OperationLog:
    """写入一条操作日志并立即提交。

    独立提交是为了保证审计记录不因后续业务回滚而丢失。
    """
    log = OperationLog(
        user_id=user_id,
        action=action,
        target=target,
        detail=detail,
        ip=ip,
    )
    db.add(log)
    await db.commit()
    await db.refresh(log)
    return log


async def write_log_safe(
    db: AsyncSession,
    *,
    user_id: int | None,
    action: str,
    target: str | None = None,
    detail: str | None = None,
    ip: str | None = None,
) -> None:
    """写入失败不影响主流程的版本（审计异常不应阻断业务）。"""
    try:
        await write_log(
            db,
            user_id=user_id,
            action=action,
            target=target,
            detail=detail,
            ip=ip,
        )
    except Exception:  # noqa: BLE001  审计失败仅记录，不向上抛出
        await db.rollback()

"""安全工具：密码哈希与 JWT 签发/校验。

密码使用 bcrypt 原生 API（不使用 passlib：其已停止维护，且与 bcrypt 5.x 不兼容）。
JWT 使用 python-jose，载荷包含用户 ID 与角色，供 require_role 做权限判定。
"""

from datetime import UTC, datetime, timedelta

import bcrypt
from jose import JWTError, jwt

from app.config import settings

# bcrypt 只处理前 72 字节，超出部分直接截断（与 bcrypt 官方行为一致）
BCRYPT_MAX_BYTES = 72


def hash_password(password: str) -> str:
    """生成 bcrypt 加盐哈希。"""
    raw = password.encode("utf-8")[:BCRYPT_MAX_BYTES]
    return bcrypt.hashpw(raw, bcrypt.gensalt(rounds=12)).decode("utf-8")


def verify_password(plain_password: str, password_hash: str) -> bool:
    """校验明文密码与哈希是否匹配。"""
    if not plain_password or not password_hash:
        return False
    raw = plain_password.encode("utf-8")[:BCRYPT_MAX_BYTES]
    try:
        return bcrypt.checkpw(raw, password_hash.encode("utf-8"))
    except (ValueError, TypeError):
        # 哈希串本身损坏或非法编码
        return False


def create_access_token(
    user_id: int,
    role: str,
    expires_minutes: int | None = None,
) -> str:
    """签发访问令牌，载荷含 sub（用户ID）、role、iat、exp。"""
    now = datetime.now(UTC)
    expire = now + timedelta(
        minutes=expires_minutes
        if expires_minutes is not None
        else settings.access_token_expire_minutes
    )
    payload = {
        "sub": str(user_id),
        "role": role,
        "iat": int(now.timestamp()),
        "exp": int(expire.timestamp()),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> dict | None:
    """解析并校验令牌，失败返回 None（不抛异常，由调用方决定如何响应）。"""
    if not token:
        return None
    try:
        return jwt.decode(
            token, settings.jwt_secret, algorithms=[settings.jwt_algorithm]
        )
    except JWTError:
        return None


def token_expire_seconds() -> int:
    """令牌有效期（秒），供登录接口返回。"""
    return settings.access_token_expire_minutes * 60

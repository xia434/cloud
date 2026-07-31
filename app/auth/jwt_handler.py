"""JWT 签发与验证 (P3 安全认证体系)。

使用 PyJWT 实现 HS256 签名，未安装 PyJWT 时给出明确错误。
严格模式：token 过期/无效/篡改均抛对应异常，由 dependency 层转 HTTP 401。
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Any

try:
    import jwt  # PyJWT
except ImportError as e:  # pragma: no cover
    raise ImportError(
        "PyJWT is required for authentication: pip install PyJWT"
    ) from e


class TokenExpiredError(Exception):
    """token 已过期。"""


class InvalidTokenError(Exception):
    """token 无效（签名错误/格式错误/缺失）。"""


def _get_settings():
    """惰性加载 settings，避免模块导入时触发 .env 校验。"""
    # agent/config 是通过 sys.path 注入的，确保在这里可访问
    from config import get_settings
    return get_settings()


def create_access_token(
    user_id: str,
    extra_claims: dict[str, Any] | None = None,
) -> str:
    """签发 JWT。

    Args:
        user_id: 用户标识（sub claim）
        extra_claims: 额外 claim（如 role）

    Returns:
        编码后的 JWT 字符串
    """
    settings = _get_settings()
    now = datetime.now(timezone.utc)
    payload: dict[str, Any] = {
        "sub": user_id,
        "iat": now,
        "exp": now + timedelta(hours=settings.jwt_expire_hours),
    }
    if extra_claims:
        payload.update(extra_claims)
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> dict[str, Any]:
    """验证并解码 JWT。

    Args:
        token: JWT 字符串

    Returns:
        解码后的 payload dict

    Raises:
        TokenExpiredError: token 已过期
        InvalidTokenError: token 无效
    """
    settings = _get_settings()
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=[settings.jwt_algorithm],
        )
    except jwt.ExpiredSignatureError as e:
        raise TokenExpiredError("token expired") from e
    except jwt.PyJWTError as e:
        raise InvalidTokenError(f"invalid token: {e}") from e

    sub = payload.get("sub")
    if not sub or not isinstance(sub, str):
        raise InvalidTokenError("token missing valid 'sub' claim")
    return payload

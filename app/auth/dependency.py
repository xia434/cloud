"""FastAPI 认证依赖 (P3 安全认证体系)。

提供 Depends 可注入的依赖：
- get_current_user_id: 从 Authorization header 解析 JWT，返回 user_id
- require_user_id: 同上，但显式语义（保留以兼容未来 RBAC 扩展）

严格模式：未携 token / token 无效 / token 过期 一律抛 HTTPException(401)。
"""
from __future__ import annotations

from fastapi import Depends, Header, HTTPException, status

from .jwt_handler import decode_access_token, InvalidTokenError, TokenExpiredError
from .models import get_user_by_id


def get_current_user_id(
    authorization: str | None = Header(default=None, description="Bearer <token>"),
) -> str:
    """从 Authorization header 解析 JWT，返回 user_id。

    严格模式：缺失/无效/过期均 401。
    """
    if not authorization:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authorization header missing",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # 期望格式: Bearer <token>
    parts = authorization.split(" ", 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authorization header must be 'Bearer <token>'",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = parts[1].strip()
    try:
        payload = decode_access_token(token)
    except TokenExpiredError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="token expired, please login again",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except InvalidTokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user_id = payload["sub"]
    # 二次校验：确保 user_id 仍存在于用户表（防止已删除用户的 token 继续生效）
    if get_user_by_id(user_id) is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="user no longer exists",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user_id


# 语义别名：当前与 get_current_user_id 等价，保留以兼容未来 RBAC 扩展
require_user_id = get_current_user_id

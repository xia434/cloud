"""认证模块 (P3 安全认证体系)。

提供 JWT 签发/验证、mock 用户表、FastAPI 依赖注入。
严格模式：未携带有效 token 的请求一律 401。
"""
from .jwt_handler import create_access_token, decode_access_token, TokenExpiredError, InvalidTokenError
from .models import mock_user_db, authenticate_user, get_user_by_id
from .dependency import get_current_user_id, require_user_id

__all__ = [
    "create_access_token",
    "decode_access_token",
    "TokenExpiredError",
    "InvalidTokenError",
    "mock_user_db",
    "authenticate_user",
    "get_user_by_id",
    "get_current_user_id",
    "require_user_id",
]

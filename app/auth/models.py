"""Mock 用户表 (P3 安全认证体系)。

本实现用内存 dict + 预先 hash 好的密码，便于本地开发和功能验证。

3 个测试账号（与 mock_data/数据库中的 user_1001/1002/1003 对齐）：
- user_1001 / cloud@2024
- user_1002 / cloud@2024
- user_1003 / cloud@2024

密码 hash 直接用 bcrypt 库（passlib 1.7.4 与 bcrypt 5.x 不兼容，故绕过 passlib）。
未安装 bcrypt 时降级到 sha256 + salt。
"""
from __future__ import annotations

import os
import hashlib
import secrets
from dataclasses import dataclass
from typing import Optional

# 优先用 bcrypt 库（直接调用，不经过 passlib，避免兼容性问题）
try:
    import bcrypt as _bcrypt
    _HAS_BCRYPT = True
except ImportError:  # pragma: no cover
    _bcrypt = None
    _HAS_BCRYPT = False
    print("[AUTH] Warning: bcrypt not installed, falling back to sha256")


@dataclass
class User:
    user_id: str
    username: str
    password_hash: str
    display_name: str
    role: str = "user"  # "user" | "admin"


def _hash_password(password: str) -> str:
    if _HAS_BCRYPT:
        # bcrypt 限制密码 ≤ 72 bytes，这里截断（演示场景密码都很短）
        pwd_bytes = password.encode("utf-8")[:72]
        salt = _bcrypt.gensalt()
        return _bcrypt.hashpw(pwd_bytes, salt).decode("utf-8")
    # 降级路径：sha256 + 固定 salt（仅用于本地调试，生产必须用 bcrypt）
    salt = "cloud_agent_static_salt_for_dev_only"
    return hashlib.sha256(f"{salt}:{password}".encode()).hexdigest()


def _verify_password(password: str, password_hash: str) -> bool:
    if _HAS_BCRYPT:
        pwd_bytes = password.encode("utf-8")[:72]
        hash_bytes = password_hash.encode("utf-8")
        try:
            return _bcrypt.checkpw(pwd_bytes, hash_bytes)
        except (ValueError, TypeError):
            return False
    salt = "cloud_agent_static_salt_for_dev_only"
    return secrets.compare_digest(
        hashlib.sha256(f"{salt}:{password}".encode()).hexdigest(),
        password_hash,
    )


# Mock 用户表 - 与 billing/orders 数据库中的 user_id 对齐
# 密码统一为 cloud@2024（演示用），hash 在模块加载时计算
_DEFAULT_PASSWORD = "cloud@2024"
_HASH = _hash_password(_DEFAULT_PASSWORD)

mock_user_db: dict[str, User] = {
    "user_1001": User(
        user_id="user_1001",
        username="alice",
        password_hash=_HASH,
        display_name="Alice (产品经理)",
        role="user",
    ),
    "user_1002": User(
        user_id="user_1002",
        username="bob",
        password_hash=_HASH,
        display_name="Bob (运维工程师)",
        role="user",
    ),
    "user_1003": User(
        user_id="user_1003",
        username="admin",
        password_hash=_HASH,
        display_name="Admin (管理员)",
        role="admin",
    ),
}

# 用户名 → user_id 索引
_USERNAME_INDEX: dict[str, str] = {u.username: uid for uid, u in mock_user_db.items()}


def authenticate_user(username: str, password: str) -> Optional[User]:
    """用户名 + 密码验证。成功返回 User，失败返回 None。"""
    user_id = _USERNAME_INDEX.get(username)
    if user_id is None:
        return None
    user = mock_user_db[user_id]
    if not _verify_password(password, user.password_hash):
        return None
    return user


def get_user_by_id(user_id: str) -> Optional[User]:
    """按 user_id 查询用户。"""
    return mock_user_db.get(user_id)

"""认证路由 (P3 安全认证体系)。

提供登录签发 JWT 与当前用户信息查询。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from auth.jwt_handler import create_access_token
from auth.models import authenticate_user, get_user_by_id
from auth.dependency import get_current_user_id

router = APIRouter()


class LoginRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=64)
    password: str = Field(..., min_length=1, max_length=128)


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user_id: str
    username: str
    display_name: str
    role: str


class UserInfoResponse(BaseModel):
    user_id: str
    username: str
    display_name: str
    role: str


@router.post("/auth/login", response_model=LoginResponse)
async def login(request: LoginRequest):
    """用户名 + 密码登录，签发 JWT。

    严格模式：失败一律返回 401（不区分用户名错误/密码错误，防止用户名枚举）。
    """
    user = authenticate_user(request.username, request.password)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    token = create_access_token(
        user_id=user.user_id,
        extra_claims={"role": user.role, "username": user.username},
    )
    return LoginResponse(
        access_token=token,
        user_id=user.user_id,
        username=user.username,
        display_name=user.display_name,
        role=user.role,
    )


@router.get("/auth/me", response_model=UserInfoResponse)
async def me(user_id: str = Depends(get_current_user_id)):
    """获取当前登录用户信息（需携带有效 JWT）。"""
    user = get_user_by_id(user_id)
    if user is None:  # 理论上 dependency 已校验，双保险
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="user not found",
        )
    return UserInfoResponse(
        user_id=user.user_id,
        username=user.username,
        display_name=user.display_name,
        role=user.role,
    )

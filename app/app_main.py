import sys
import os

# 将 agent 目录加入 sys.path
AGENT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "agent")
sys.path.insert(0, AGENT_DIR)

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager

from router import chat
from router import health
from router import history
from router import auth
from service.chat_service import init_agent_system, shutdown_agent_system


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_agent_system()
    try:
        yield
    finally:
        await shutdown_agent_system()


app = FastAPI(title="Multi-Agent Cloud Service API", lifespan=lifespan)

# P3 安全认证体系改造：CORS 显式来源列表，禁止 '*' + allow_credentials=True 反模式
def _get_cors_origins() -> list[str]:
    try:
        from config import get_settings
        settings = get_settings()
        return [o.strip() for o in settings.cors_origins.split(",") if o.strip()]
    except Exception as e:
        # settings 加载失败时降级到只允许本地开发端口
        print(f"[CORS] Failed to load settings, fallback to localhost only: {e}")
        return ["http://localhost:5175", "http://localhost:5173"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_get_cors_origins(),
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "Accept"],
)

# 注册路由
app.include_router(chat.router, prefix="/api")
app.include_router(health.router, prefix="/api")
app.include_router(history.router, prefix="/api")
app.include_router(auth.router, prefix="/api")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app_main:app", host="0.0.0.0", port=5000, reload=True)

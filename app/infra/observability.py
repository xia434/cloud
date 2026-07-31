"""Langfuse 可观测性集成模块（v4 SDK + 自托管 langfuse:2 server）。

负责：
- 检测 Langfuse 配置是否完整
- 创建 Langfuse LangchainCallbackHandler（用于 LangChain/LangGraph 自动追踪）
- 未配置或初始化失败时优雅降级，不影响主流程

集成方式：
- LangChain/LangGraph 通过 config["callbacks"] 接收 callback handler
- 自动捕获：LLM 调用、工具调用、链式调用、Token 消耗、错误

技术说明：
- 使用 langfuse v4 SDK（``langfuse.langchain.CallbackHandler``），原生兼容
  langchain 1.x；对接自托管 langfuse:2 server（docker-compose 启动后默认
  ``http://localhost:3000``），ingestion API 与 v4 SDK 兼容
- v4 SDK 通过环境变量 ``LANGFUSE_PUBLIC_KEY``/``SECRET_KEY``/``HOST`` 自动初始化
  全局 client，CallbackHandler 不再接收 user_id/session_id 参数；这些维度
  通过 LangGraph 的 ``configurable`` 在调用时透传，由 SDK 自动从 metadata 抓取
- 前置条件：先 ``docker-compose up -d langfuse langfuse_db``，再在
  ``http://localhost:3000`` 创建 Project 并将公钥/密钥填入 .env

使用示例::

    from infra.observability import get_langfuse_callback

    handler = get_langfuse_callback()
    config = {"configurable": {"user_id": "u1", "session_id": "s1"}}
    if handler:
        config["callbacks"] = [handler]
    result = await graph.ainvoke(state, config=config)
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

# 全局单例：判断 Langfuse 是否可用
_langfuse_available: bool | None = None
_langfuse_init_error: str | None = None


def _check_langfuse_config() -> bool:
    """检查 Langfuse 配置是否完整（公钥 + 密钥）。"""
    global _langfuse_available, _langfuse_init_error
    if _langfuse_available is not None:
        return _langfuse_available

    try:
        from config import get_settings
        settings = get_settings()
        public_key = settings.langfuse_public_key
        secret_key = settings.langfuse_secret_key
        if not public_key or not secret_key:
            _langfuse_available = False
            _langfuse_init_error = "LANGFUSE_PUBLIC_KEY 或 LANGFUSE_SECRET_KEY 未配置"
            logger.info("[OBSERVABILITY] Langfuse 未启用：%s", _langfuse_init_error)
            return False
        _langfuse_available = True
        return True
    except Exception as e:
        _langfuse_available = False
        _langfuse_init_error = str(e)
        logger.warning("[OBSERVABILITY] Langfuse 配置检查失败：%s", e)
        return False


def get_langfuse_callback(
    user_id: str | None = None,
    session_id: str | None = None,
    trace_name: str = "cloud_agent_chat",
    metadata: dict[str, Any] | None = None,
):
    """获取 Langfuse LangchainCallbackHandler（如果可用）。

    Args:
        user_id: 用户标识（v4 SDK 通过 LangGraph metadata 抓取，这里仅用于日志）
        session_id: 会话标识（同上）
        trace_name: trace 名称（v4 SDK 不直接支持，仅在日志中记录）
        metadata: 附加元数据（v4 SDK 通过 LangGraph metadata 抓取）

    Returns:
        langfuse.langchain.CallbackHandler 实例，或 None（未启用时）
    """
    if not _check_langfuse_config():
        return None

    try:
        # v4 入口：langfuse.langchain.CallbackHandler
        # 通过环境变量自动初始化 client，原生兼容 langchain 1.x
        from langfuse.langchain import CallbackHandler

        handler = CallbackHandler()
        logger.info(
            "[OBSERVABILITY] Langfuse callback 已创建: trace=%s user=%s session=%s",
            trace_name, user_id, session_id,
        )
        return handler
    except ImportError:
        _langfuse_available = False
        _langfuse_init_error = "langfuse 包未安装（pip install langfuse）"
        logger.warning("[OBSERVABILITY] %s", _langfuse_init_error)
        return None
    except Exception as e:
        _langfuse_available = False
        _langfuse_init_error = str(e)
        logger.warning("[OBSERVABILITY] Langfuse 初始化失败：%s", e)
        return None


def is_observability_enabled() -> bool:
    """返回 Langfuse 是否启用。供外部诊断使用。"""
    if _langfuse_available is None:
        _check_langfuse_config()
    return bool(_langfuse_available)


def get_observability_status() -> dict[str, Any]:
    """获取可观测性状态，供 /health 等诊断接口使用。"""
    return {
        "enabled": is_observability_enabled(),
        "error": _langfuse_init_error,
    }

"""LLM 工厂：创建带重试机制的 ChatOpenAI 实例（P2-10 改造）。

原问题：所有 Agent 直接 `ChatOpenAI(...)` 创建 LLM，没有重试机制。
        高并发或网络抖动时，单次 LLM 调用失败会导致整个 Agent 流程崩溃。

改造方案：
- 用 tenacity 包装 ChatOpenAI 的 invoke/ainvoke/stream/astream 方法
- 仅对可重试异常重试（网络错误、5xx、429 限流），不重试业务错误（4xx 鉴权失败）
- 指数退避 + 最大 3 次重试
- 各 Agent 改用 create_llm_with_retry() 替代直接 ChatOpenAI()

使用示例::

    from core.llm_factory import create_llm_with_retry
    llm = create_llm_with_retry(model="qwen-plus", temperature=0.1)
    response = await llm.ainvoke([HumanMessage(content="hi")])
"""
from __future__ import annotations

import logging
from typing import Any

from langchain_openai import ChatOpenAI
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
    before_sleep_log,
)

logger = logging.getLogger(__name__)


# 可重试的异常类型（网络/限流/服务端错误）
# 注意：openai.AuthenticationError 等 4xx 错误不在此列，不会重试
_RETRYABLE_EXCEPTIONS: tuple[type[BaseException], ...] = (
    # 通用网络错误
    ConnectionError,
    TimeoutError,
    OSError,
)

# 尝试追加 openai 库的可重试异常
try:
    import openai
    _RETRYABLE_EXCEPTIONS = (
        *_RETRYABLE_EXCEPTIONS,
        openai.APITimeoutError,
        openai.APIConnectionError,
        openai.RateLimitError,
        openai.InternalServerError,
    )
except ImportError:
    pass


def _create_retry_decorator():
    """创建 tenacity 重试装饰器。"""
    return retry(
        retry=retry_if_exception_type(_RETRYABLE_EXCEPTIONS),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=8),
        before_sleep=before_sleep_log(logger, logging.WARNING),
        reraise=True,  # 重试耗尽后抛出原始异常
    )


def _wrap_llm_with_retry(llm: Any) -> Any:
    """对一个 LLM 实例（或其 bind_tools 返回的 RunnableBinding）应用重试装饰。

    P0 修复：原实现只包装顶层 llm 的方法，但 create_react_agent 内部会调
    llm.bind_tools(tools) 返回新的 RunnableBinding 实例，新实例的 invoke/ainvoke
    不继承被替换的方法，导致重试失效。

    修复策略：
    - 对 RunnableBinding，包装其绑定的底层 runnable（bound）的 generate/agenerate
    - 同时包装 RunnableBinding 自身的 invoke/ainvoke/stream/astream 作为兜底
    - 这样无论 LangGraph 走哪条调用路径（直接 invoke 或经 bind_tools），重试都能生效
    """
    retry_decorator = _create_retry_decorator()

    # 情况 1：RunnableBinding（bind_tools 返回的实例）
    if hasattr(llm, "bound") and hasattr(llm, "invoke"):
        try:
            # 包装底层 bound runnable 的核心方法
            bound = llm.bound
            if hasattr(bound, "invoke"):
                object.__setattr__(bound, "invoke", retry_decorator(bound.invoke))
            if hasattr(bound, "ainvoke"):
                object.__setattr__(bound, "ainvoke", retry_decorator(bound.ainvoke))
            if hasattr(bound, "stream"):
                object.__setattr__(bound, "stream", retry_decorator(bound.stream))
            if hasattr(bound, "astream"):
                object.__setattr__(bound, "astream", retry_decorator(bound.astream))
        except (AttributeError, TypeError):
            # 某些 Runnable 子类可能不允许 __setattr__，忽略
            pass
        return llm

    # 情况 2：普通 ChatOpenAI 实例
    try:
        object.__setattr__(llm, "invoke", retry_decorator(llm.invoke))
        object.__setattr__(llm, "ainvoke", retry_decorator(llm.ainvoke))
        object.__setattr__(llm, "stream", retry_decorator(llm.stream))
        object.__setattr__(llm, "astream", retry_decorator(llm.astream))
        object.__setattr__(llm, "astream_events", retry_decorator(llm.astream_events))
    except (AttributeError, TypeError):
        pass

    return llm


def create_llm_with_retry(
    model: str = "qwen-plus",
    temperature: float = 0.7,
    api_key: str | None = None,
    base_url: str | None = None,
    **kwargs: Any,
) -> ChatOpenAI:
    """创建带重试机制的 ChatOpenAI 实例。

    Args:
        model: 模型名（默认 qwen-plus）
        temperature: 温度参数
        api_key: API Key（默认从环境变量 DASHSCOPE_API_KEY 读取）
        base_url: API Base URL（默认通义千问兼容端点）
        **kwargs: 其他传给 ChatOpenAI 的参数

    Returns:
        ChatOpenAI 实例，其 invoke/ainvoke/stream/astream 方法已包装重试。
        同时 hook 了 bind_tools 方法，确保 create_react_agent 内部调用
        bind_tools 返回的新实例也带有重试机制。
    """
    import os

    api_key = api_key or os.getenv("DASHSCOPE_API_KEY")
    base_url = base_url or os.getenv(
        "BASE_URL",
        "https://dashscope.aliyuncs.com/compatible-mode/v1",
    )

    llm = ChatOpenAI(
        model=model,
        temperature=temperature,
        api_key=api_key,
        base_url=base_url,
        **kwargs,
    )

    # 1. 先包装 llm 自身的方法（用于直接 invoke/ainvoke 的场景）
    _wrap_llm_with_retry(llm)

    # 2. P0 修复：hook bind_tools，让返回的新实例也带重试
    # 原问题：create_react_agent 内部调 llm.bind_tools(tools) 返回新 RunnableBinding，
    #         新实例不继承被替换的方法，重试失效。
    # 修复：包装 bind_tools，让它在返回前对新实例应用 _wrap_llm_with_retry
    original_bind_tools = llm.bind_tools
    def _patched_bind_tools(*args, **kw):
        new_binding = original_bind_tools(*args, **kw)
        return _wrap_llm_with_retry(new_binding)
    object.__setattr__(llm, "bind_tools", _patched_bind_tools)

    return llm

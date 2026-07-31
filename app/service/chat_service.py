import asyncio
import json
import sys
import os
from typing import Any

# 初始化 Agent 和 Graph
AGENT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "agent")
if AGENT_DIR not in sys.path:
    sys.path.insert(0, AGENT_DIR)

from core.workflow.graph_manager import AgentGraphManager
from core.memory.memory_manager import MemoryManager
from infra.cache import semantic_cache
from infra.observability import get_langfuse_callback
from service.stream_policy import (
    FINAL_RESPONSE_NODES,
    extract_final_response_text,
    is_stable_knowledge_query,
    should_forward_model_event,
)

# Global variables for graph and memory
graph = None
memory = None

# P1-4 修复：保存后台任务引用，防止被 GC 回收导致偏好提取被静默取消
# Python 官方警告：create_task 返回的 Task 必须保存引用，否则可能被垃圾回收
_background_tasks: set[asyncio.Task] = set()


def _schedule_background_task(coro) -> None:
    """调度后台任务并保存引用，任务完成后自动清理引用。"""
    task = asyncio.create_task(coro)
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)

async def init_agent_system():
    global graph, memory
    if graph is None:
        print("[INIT] 初始化 Multi-Agent 图编排...")
        graph_manager = AgentGraphManager()
        graph = graph_manager.build_graph()

        print("[INIT] 初始化 Memory 系统...")
        from config import get_settings
        settings = get_settings()
        # 创建摘要压缩用的 LLM（复用主模型，temperature=0 保证摘要稳定）
        from core.llm_factory import create_llm_with_retry
        import os as _os
        summary_llm = create_llm_with_retry(
            model=_os.getenv("MODEL", "qwen-plus"),
            api_key=_os.getenv("DASHSCOPE_API_KEY"),
            base_url=_os.getenv("BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1"),
            temperature=0,
        )
        memory = MemoryManager(
            redis_url=settings.redis_url,
            redis_ttl=settings.redis_ttl,
            milvus_host=settings.milvus_host,
            milvus_port=settings.milvus_port,
            milvus_api_key=settings.milvus_api_key,
            embedding_api_key=settings.dashscope_api_key,
            summary_llm=summary_llm,
        )
        await memory.initialize()
        await semantic_cache.initialize()
        print("[INIT] Agent 系统初始化完成！")


async def shutdown_agent_system() -> None:
    """Drain background work and close external clients on application exit."""
    global graph, memory

    pending = [task for task in _background_tasks if not task.done()]
    if pending:
        done, still_pending = await asyncio.wait(pending, timeout=10)
        for task in still_pending:
            task.cancel()
        if still_pending:
            await asyncio.gather(*still_pending, return_exceptions=True)

    if memory is not None:
        try:
            await memory.close()
        except Exception as exc:
            print(f"[SHUTDOWN] Memory close failed: {exc}")

    await semantic_cache.close()

    # Langfuse batches events. Flush best-effort so deploy/restart does not lose
    # the final traces; observability must never block application shutdown.
    try:
        from langfuse import get_client

        await asyncio.wait_for(asyncio.to_thread(get_client().flush), timeout=5)
    except Exception as exc:
        print(f"[SHUTDOWN] Langfuse flush skipped/failed: {exc}")

    graph = None
    memory = None

async def _extract_memory_context(user_id: str, session_id: str, query: str) -> str:
    """注入记忆上下文（短期历史 + 长期偏好/事实）。

    设计说明：
    - 始终注入短期历史：Orchestrator 路由决策依赖上下文，短查询（如"java web"）
      若无上文会被误判为 OOD。Redis 读取毫秒级，10 条历史约 500-1000 token，
      性能开销可忽略，上下文连贯性优先于 token 节省。
    - 长期记忆始终注入（偏好 + 事实，数据量小、价值高，用于个性化所有回复）。
    """
    context_parts = []

    # 始终注入短期历史（Orchestrator 路由 + 业务 Agent 回答都依赖上下文）
    if memory and memory.short_term.available:
        history = await memory.short_term.get_messages(user_id, session_id)
        if history:
            recent_history = history[-10:] if len(history) > 10 else history
            context_parts.append("【近期对话历史】:")
            for msg in recent_history:
                role = "User" if msg["role"] == "user" else "Assistant"
                context_parts.append(f"{role}: {msg['content']}")

    # 长期记忆始终注入（偏好 + 事实，分别召回，数据量小、价值高）
    if memory and memory.long_term.available:
        # 召回用户偏好（长期稳定的习惯）
        prefs = await memory.long_term.retrieve_relevant(
            user_id, query, top_k=3, memory_type="preference"
        )
        if prefs:
            context_parts.append("\n【用户偏好】:")
            for p in prefs:
                context_parts.append(f"- {p}")
        # 召回任务相关事实（当前任务的关键上下文）
        facts = await memory.long_term.retrieve_relevant(
            user_id, query, top_k=3, memory_type="fact"
        )
        if facts:
            context_parts.append("\n【任务相关事实】:")
            for f in facts:
                context_parts.append(f"- {f}")

    return "\n".join(context_parts)

def _sse(payload: dict) -> str:
    """将 dict 序列化为 SSE 数据行。"""
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"

async def stream_chat(query: str, user_id: str, session_id: str):
    """流式聊天主入口。

    改造说明（P0-1 真流式改造）：
    - 原实现：graph.ainvoke() 同步等待完整结果，再切片 yield（伪流式，
      首字延迟 = 整个 Agent 推理时间）。
    - 新实现：graph.astream_events(version="v2") 监听 LLM token 流，
      实现 token 级真流式，首字延迟 ≈ LLM 首 token 延迟。
    - 同时输出路由、工具调用等元数据事件，前端可选择性展示思考过程。
    - 缓存命中场景仍走切片流式（缓存里存的是完整文本）。
    - 修复原实现未写入语义缓存的 bug（set_cache 调用缺失）。
    """
    # 1. 仅稳定的产品知识问答允许走语义缓存。账单、实例、FinOps、推荐和
    # 营销结果具有用户态或时效性，缓存会造成越权或过期答案。
    cache_candidate = is_stable_knowledge_query(query)
    cache_hit = (
        await semantic_cache.get_cache(query, user_id)
        if cache_candidate
        else None
    )

    response_text = ""
    selected_agent = ""
    stream_failed = False

    if cache_hit:
        # 缓存命中：走切片流式
        response_text = cache_hit["answer"]
        print(
            f"[CACHE] 语义缓存命中: {cache_hit['level']} "
            f"distance={cache_hit['distance']:.4f} "
            f"matched='{cache_hit['matched_question']}'"
        )
        yield _sse({
            "type": "cache_hit",
            "level": cache_hit["level"],
            "matched_question": cache_hit["matched_question"],
        })
        chunk_size = 8
        for i in range(0, len(response_text), chunk_size):
            chunk = response_text[i:i + chunk_size]
            yield _sse({"content": chunk})
            await asyncio.sleep(0.02)
    else:
        # 2. 进入 Agent 真流式推理
        print("[AGENT] 进入 Agent 工作流推理（真流式 astream_events）...")
        mem_context = await _extract_memory_context(user_id, session_id, query)
        state = {
            "messages": [("user", query)],
            "user_id": user_id,
            "session_id": session_id,
            "memory_context": mem_context,
            "next_agent": "",
            "metadata": {}
        }
        # thread_id 是 LangGraph checkpointer 的会话隔离标识
        # 用 user_id:session_id 组合，确保不同用户、不同会话的 state 完全隔离
        trace_name = f"chat:{query[:30]}"
        config = {
            "configurable": {
                "user_id": user_id,
                "thread_id": f"{user_id}:{session_id}",
            },
            "metadata": {
                "user_id": user_id,
                "session_id": session_id,
                "trace_name": trace_name,
                "langfuse_user_id": user_id,
                "langfuse_session_id": session_id,
                "langfuse_trace_name": trace_name,
                "query": query[:200],
            },
        }

        # 注入 Langfuse 可观测性 callback（未启用时返回 None，不影响主流程）
        langfuse_handler = get_langfuse_callback(
            user_id=user_id,
            session_id=session_id,
            trace_name=trace_name,
            metadata={"query": query[:200]},
        )
        if langfuse_handler:
            config["callbacks"] = [langfuse_handler]

        # 3. 用 astream_events 监听细粒度事件
        try:
            async for event in graph.astream_events(state, config=config, version="v2"):
                kind = event["event"]
                name = event.get("name", "")
                data = event.get("data", {})

                # 3.1 路由完成事件（Orchestrator 节点结束 → 通知前端路由结果）
                if kind == "on_chain_end" and name == "orchestrator":
                    output = data.get("output", {})
                    if isinstance(output, dict):
                        next_agent = output.get("next_agent", "")
                        if next_agent:
                            selected_agent = next_agent
                            yield _sse({"type": "route", "agent": next_agent})

                # 固定文案兜底不会产生 on_chat_model_stream。业务节点结束时，
                # 若此前没有输出任何 token，则回收节点最终 AIMessage。
                elif kind == "on_chain_end" and name in FINAL_RESPONSE_NODES:
                    if not response_text:
                        final_text = extract_final_response_text(data.get("output"))
                        if final_text:
                            response_text = final_text
                            yield _sse({"content": final_text})

                # 3.2 工具调用事件（让前端展示 Agent 正在调用哪个工具）
                elif kind == "on_tool_start":
                    tool_input = data.get("input", {})
                    args_summary: dict[str, Any] = {}
                    if isinstance(tool_input, dict):
                        for k, v in tool_input.items():
                            if isinstance(v, str) and len(v) > 200:
                                args_summary[k] = v[:200] + "..."
                            else:
                                args_summary[k] = v
                    yield _sse({
                        "type": "tool_start",
                        "name": name,
                        "args": args_summary,
                    })
                elif kind == "on_tool_end":
                    output = data.get("output", "")
                    output_str = str(output)
                    if len(output_str) > 500:
                        output_str = output_str[:500] + "..."
                    yield _sse({
                        "type": "tool_end",
                        "name": name,
                        "output_preview": output_str,
                    })

                # 3.3 LLM token 流（真正的流式输出）
                elif kind == "on_chat_model_stream":
                    if not should_forward_model_event(event):
                        continue
                    chunk = data.get("chunk")
                    if (
                        chunk
                        and hasattr(chunk, "content")
                        and isinstance(chunk.content, str)
                        and chunk.content
                    ):
                        # 跳过纯 tool_call 决策的 chunk（content 为空或仅含 tool_call_chunks）
                        tool_call_chunks = getattr(chunk, "tool_call_chunks", None)
                        if tool_call_chunks:
                            continue
                        response_text += chunk.content
                        yield _sse({"content": chunk.content})
        except Exception as e:
            stream_failed = True
            print(f"[STREAM] 流式推理异常: {e}")
            import traceback
            traceback.print_exc()
            if not response_text:
                # P1-7 修复：不向用户泄露内部异常信息（可能含 API Key 片段、连接串等）
                # 仅返回通用友好提示，详细错误写服务端日志
                yield _sse({
                    "content": "\n\n[系统提示] 系统暂时繁忙，请稍后重试。"
                })

    # 4. 保存短期记忆到 Redis
    # 说明：checkpointer 已自动持久化整个 state（含 messages），此处保留 Redis 写入
    # 是因为 background_extract（偏好提取）依赖 Redis 中的消息做 LLM 提取输入
    # （memory_manager.background_extract → short_term.get_messages）。
    # 若后续将偏好提取改为从 checkpointer 读取 state，可彻底移除此 Redis 写入。
    if memory and memory.short_term.available and response_text:
        turn = [
            {"role": "user", "content": query},
            {"role": "assistant", "content": response_text},
        ]
        try:
            await memory.save_conversation(user_id, session_id, turn)
        except Exception as e:
            print(f"[MEMORY] 保存短期记忆失败: {e}")

    # 5. 写入语义缓存（修复原实现未写入缓存的 bug；仅 Agent 推理路径写入）
    if (
        not cache_hit
        and response_text
        and not stream_failed
        and cache_candidate
        and selected_agent == "product_agent"
    ):
        try:
            await semantic_cache.set_cache(query, response_text, user_id)
        except Exception as e:
            print(f"[CACHE] 写入语义缓存失败: {e}")

    # 6. 后台触发长期记忆偏好提取（P0 修复：原 PreferenceExtractor 从未接入主流程）
    # 设计说明：
    # - 用 background_extract 而非 finalize_session，因为 finalize 会清空 Redis 短期记忆，
    #   不适合每轮调用；background_extract 只提取偏好不清空，适合持续会话。
    # - 用 asyncio.create_task 后台执行，不阻塞 SSE done 事件，用户无感知。
    # - 提取需要 LLM，这里复用 Orchestrator 的 LLM（轻量分类模型，足够提取偏好）。
    # - 仅在 Milvus 可用 + 有响应文本时触发，避免无意义调用。
    if memory and memory.long_term.available and response_text and not cache_hit:
        try:
            from core.llm_factory import create_llm_with_retry
            import os as _os
            extract_llm = create_llm_with_retry(
                model=_os.getenv("MODEL", "qwen-plus"),
                api_key=_os.getenv("DASHSCOPE_API_KEY"),
                base_url=_os.getenv("BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1"),
                temperature=0.1,
            )
            # 后台执行，不等待完成（失败仅记日志，不影响主流程）
            # P1-4 修复：用 _schedule_background_task 保存引用，防止 Task 被 GC 回收
            _schedule_background_task(
                memory.background_extract(user_id, session_id, extract_llm)
            )
            print(f"[MEMORY] 已调度后台偏好提取任务: user={user_id}, session={session_id}")
        except Exception as e:
            print(f"[MEMORY] 调度后台偏好提取失败: {e}")

    # 7. 结束标记
    yield _sse({"done": True})

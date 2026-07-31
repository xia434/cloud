import os
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, AIMessage
from langgraph.prebuilt import create_react_agent
from langchain_mcp_adapters.client import MultiServerMCPClient
from typing import Dict, Any

from core.workflow.state import AgentState
from agents.billing_agent import UserIdInjector # 复用安全拦截器，防止越权刷单

class PromotionAgentNode:
    """
    推广 Agent：负责处理用户的产品分享、返佣、活动查询和推广物料获取请求。
    所有的工具调用都通过 FastMCP 服务从后端营销系统中获取。
    """
    def __init__(self):
        dotenv_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), '.env')
        load_dotenv(dotenv_path)

        # P2-10: 使用带重试机制的 LLM 工厂（替代直接 ChatOpenAI）
        from core.llm_factory import create_llm_with_retry
        self.llm = create_llm_with_retry(
            model=os.getenv("MODEL", "qwen-plus"),
            api_key=os.getenv("DASHSCOPE_API_KEY"),
            base_url=os.getenv("BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1"),
            temperature=0.3, # 营销话术可以稍微有一点创造性
        )
        
        # P1: 路径动态化 — 不再硬编码 python 绝对路径，由 load_mcp_servers_config
        # 展开 ${PYTHON_EXEC}（默认 sys.executable，保证子进程依赖一致）
        from config.settings import load_mcp_servers_config
        self.servers_config = load_mcp_servers_config()

    async def __call__(self, state: AgentState) -> Dict[str, Any]:
        config = {"configurable": {"user_id": state.get("user_id", "unknown")}}

        print("📢 [PromotionAgent] 正在生成营销与推广物料...")

        try:
            # 每次调用重新初始化 MCP 客户端，避免使用不支持的 async with
            client = MultiServerMCPClient(
                connections=self.servers_config.get("mcpServers", {}),
                tool_interceptors=[UserIdInjector()]
            )
            all_tools = await client.get_tools()
            target_tools = ["get_promotable_products", "search_product_catalog", "get_promotion_materials", "generate_ai_poster"]
            tools = [t for t in all_tools if t.name in target_tools]

            memory_context = state.get("memory_context", "")

            # P1-8: Prompt 抽离到 prompts/templates.py 统一管理
            from prompts.templates import PROMOTION_AGENT_PROMPT, PROMOTION_FALLBACK_PROMPT, format_memory_context
            system_prompt = PROMOTION_AGENT_PROMPT.format(
                memory_context=format_memory_context(memory_context)
            )
            inner_agent = create_react_agent(
                model=self.llm,
                tools=tools,
                prompt=system_prompt
            )

            result = await inner_agent.ainvoke(
                {"messages": state["messages"]},
                config=config
            )

            final_message = result["messages"][-1]
        except Exception as e:
            # 工具调用失败兜底：用 PROMOTION_FALLBACK_PROMPT 让 LLM 给业务友好回复，
            # 不向用户暴露内部错误信息（异常堆栈、错误码等）
            print(f"⚠️ [PromotionAgent] 工具调用失败，使用兜底 Prompt 回答: {str(e)}")
            from prompts.templates import PROMOTION_FALLBACK_PROMPT
            try:
                response = await self.llm.ainvoke([
                    SystemMessage(content=PROMOTION_FALLBACK_PROMPT)
                ])
                content = str(response.content).strip()
                final_message = AIMessage(content=content or "推广服务暂时无法返回结果，请稍后重试。")
            except Exception as fallback_error:
                print(f"⚠️ [PromotionAgent] 兜底 LLM 也失败: {str(fallback_error)}")
                final_message = AIMessage(
                    content="抱歉，推广活动与海报服务当前暂时不可用，请稍后重试。"
                )

        return {"messages": [final_message]}

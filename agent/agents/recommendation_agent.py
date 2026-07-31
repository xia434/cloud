import os
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, AIMessage
from langgraph.prebuilt import create_react_agent
from core.workflow.state import AgentState
from typing import Dict, Any
from langchain_mcp_adapters.client import MultiServerMCPClient
from agents.billing_agent import UserIdInjector
from tools.vector_tool import query_vector_db
# P1-8: Prompt 抽离到 prompts/templates.py 统一管理
from prompts.templates import RECOMMENDATION_AGENT_PROMPT, RECOMMENDATION_FALLBACK_PROMPT, format_memory_context

class RecommendationAgent:
    """
    智能推荐 Agent：负责根据用户的业务需求（类型、预算、并发等）进行云产品选型与推荐。
    它会调用向量数据库了解产品特性，并结合 MCP 获取真实可用的商品列表。
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
            temperature=0.3, # 推荐场景需要一点灵活性，但不宜过高
        )
        
        # P1: 路径动态化 — 不再硬编码 python 绝对路径，由 load_mcp_servers_config
        # 展开 ${PYTHON_EXEC}（默认 sys.executable，保证子进程依赖一致）
        from config.settings import load_mcp_servers_config
        self.servers_config = load_mcp_servers_config()

    async def __call__(self, state: AgentState) -> Dict[str, Any]:
        memory_context = state.get("memory_context", "")
        config = {"configurable": {"user_id": state.get("user_id", "unknown")}}

        print("🔍 [RecommendationAgent] 正在进行智能产品选型与推荐...")

        try:
            # 获取 MCP 工具（用于拉取商品库）
            client = MultiServerMCPClient(
                connections=self.servers_config.get("mcpServers", {}),
                tool_interceptors=[UserIdInjector()]
            )
            all_tools = await client.get_tools()
            # 我们需要 search_product_catalog 和 get_promotable_products 来拉取商品
            # 并引入 get_promotion_materials 获取最终的下单/推广链接
            target_tools = ["get_promotable_products", "search_product_catalog", "get_promotion_materials"]
            mcp_tools = [t for t in all_tools if t.name in target_tools]

            # 组合向量工具与 MCP 工具
            tools = [query_vector_db] + mcp_tools

            system_prompt = RECOMMENDATION_AGENT_PROMPT.format(
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
            # 工具调用失败兜底：用 RECOMMENDATION_FALLBACK_PROMPT 让 LLM 给业务友好回复，
            # 不向用户暴露内部错误信息（异常堆栈、错误码等）
            print(f"⚠️ [RecommendationAgent] 工具调用失败，使用兜底 Prompt 回答: {str(e)}")
            try:
                response = await self.llm.ainvoke([
                    SystemMessage(content=RECOMMENDATION_FALLBACK_PROMPT)
                ])
                content = str(response.content).strip()
                final_message = AIMessage(content=content or "选型服务暂时无法返回结果，请稍后重试。")
            except Exception as fallback_error:
                print(f"⚠️ [RecommendationAgent] 兜底 LLM 也失败: {str(fallback_error)}")
                final_message = AIMessage(
                    content="抱歉，产品选型服务当前暂时不可用。请稍后重试，或补充业务类型、预算和并发量后再次咨询。"
                )

        return {"messages": [final_message]}

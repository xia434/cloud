import os
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, AIMessage
from langgraph.prebuilt import create_react_agent
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_mcp_adapters.interceptors import ToolCallInterceptor, MCPToolCallRequest, MCPToolCallResult
from typing import Callable, Awaitable, Dict, Any
from core.workflow.state import AgentState

class UserIdInjector(ToolCallInterceptor):
    """
    拦截器：在真正调用 MCP 工具前，强制将 user_id 注入到参数中。
    """
    async def __call__(
        self,
        request: MCPToolCallRequest,
        handler: Callable[[MCPToolCallRequest], Awaitable[MCPToolCallResult]],
    ) -> MCPToolCallResult:
        
        # 尝试从 LangGraph 的 runtime config 中获取系统级 user_id
        user_id = None
        if hasattr(request.runtime, 'config'):
            config = request.runtime.config
            user_id = config.get("configurable", {}).get("user_id")
            
        if user_id:
            new_args = dict(request.args)
            new_args["user_id"] = user_id
            print(f"🔒 [安全拦截] 已强制注入 user_id={user_id} 到工具 {request.name}")
            new_request = request.override(args=new_args)
            return await handler(new_request)
            
        return await handler(request)

class BillingAgentNode:
    """
    包装了 MCP Client 和 create_react_agent 的节点类
    供主图编排时直接调用
    """
    def __init__(self):
        dotenv_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '.env')
        load_dotenv(dotenv_path)

        # P2-10: 使用带重试机制的 LLM 工厂（替代直接 ChatOpenAI）
        from core.llm_factory import create_llm_with_retry
        self.llm = create_llm_with_retry(
            model=os.getenv("MODEL", "qwen-plus"),
            api_key=os.getenv("DASHSCOPE_API_KEY"),
            base_url=os.getenv("BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1"),
            temperature=0.1,
        )

        # P1: 路径动态化 — 不再硬编码 python 绝对路径，由 load_mcp_servers_config
        # 展开 ${PYTHON_EXEC}（默认 sys.executable，保证子进程依赖一致）
        from config.settings import load_mcp_servers_config
        self.servers_config = load_mcp_servers_config()

    async def __call__(self, state: AgentState) -> Dict[str, Any]:
        """供主 LangGraph 调用的处理函数"""
        # 将 user_id 放入 config，以便拦截器获取
        config = {"configurable": {"user_id": state.get("user_id", "unknown")}}

        memory_context = state.get("memory_context", "")

        # P1-8: Prompt 抽离到 prompts/templates.py 统一管理
        from prompts.templates import BILLING_AGENT_PROMPT, BILLING_FALLBACK_PROMPT, format_memory_context
        system_prompt = BILLING_AGENT_PROMPT.format(
            memory_context=format_memory_context(memory_context)
        )

        print("💡 [BillingAgent] 正在处理账单与资源查询请求...")

        # 不使用 async with 语法，因为 langgraph MCP Client (0.1.0) 不支持此方法，
        # 我们采用自己维护连接的方式或者仅在用到时拉起。
        # 最简单和最稳定的方案是利用它内部支持长连接的特性，在模块级别创建，然后在生命周期内保持。
        # 为了兼容 FastAPI 的多线程/事件循环，这里我们每次新建 client 但不主动销毁（依靠垃圾回收），
        # 或者最好是通过全局依赖注入。
        # 此前报错是由于我们在 async with 中导致它被当做 context manager。

        try:
            client = MultiServerMCPClient(
                connections=self.servers_config.get("mcpServers", {}),
                tool_interceptors=[UserIdInjector()]
            )
            all_tools = await client.get_tools()
            allowed_tool_names = {"query_user_orders", "query_user_instances"}
            tools = [tool for tool in all_tools if tool.name in allowed_tool_names]

            inner_agent = create_react_agent(
                model=self.llm,
                tools=tools,
                prompt=system_prompt
            )

            result = await inner_agent.ainvoke(
                {"messages": state["messages"]},
                config=config
            )

            # 尝试清理相关子进程（如果有暴露的关闭方法，但目前版本似乎没有公开的无参 close() 或者不支持 async with）
            # client 本身在执行完毕后可能会有一些资源未释放，这是 langchain_mcp_adapters 当前版本的限制。

            final_message = result["messages"][-1]
        except Exception as e:
            # 工具调用失败兜底：用 BILLING_FALLBACK_PROMPT 让 LLM 给业务友好回复，
            # 不向用户暴露内部错误信息（异常堆栈、错误码等）
            print(f"⚠️ [BillingAgent] 工具调用失败，使用兜底 Prompt 回答: {str(e)}")
            try:
                response = await self.llm.ainvoke([
                    SystemMessage(content=BILLING_FALLBACK_PROMPT)
                ])
                content = str(response.content).strip()
                final_message = AIMessage(content=content or "账单服务暂时无法返回结果，请稍后重试。")
            except Exception as fallback_error:
                print(f"⚠️ [BillingAgent] 兜底 LLM 也失败: {str(fallback_error)}")
                final_message = AIMessage(
                    content="抱歉，账单与实例查询服务当前暂时不可用，请稍后重试或登录控制台查询。"
                )

        return {"messages": [final_message]}

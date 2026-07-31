"""
 * 小滴课堂,愿景：让技术不再难学
 * @Remark 有问题联系我【xdclass68】
 * 源码-笔记-技术交流群,官网 https://xdclass.net
"""
import os
from dotenv import load_dotenv
from langchain_core.messages import SystemMessage, AIMessage
from langgraph.prebuilt import create_react_agent
from langchain_mcp_adapters.client import MultiServerMCPClient
from typing import Dict, Any

from core.workflow.state import AgentState
from agents.billing_agent import UserIdInjector
# P1-8: Prompt 抽离到 prompts/templates.py 统一管理
from prompts.templates import FINOPS_AGENT_PROMPT, FINOPS_FALLBACK_PROMPT

class FinOpsAgentNode:
    """
    FinOps Agent：成本优化与架构诊断专家。
    负责分析用户的资源监控数据，判断是否存在资源浪费，并给出降本增效的建议。
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
            temperature=0.1,
        )
        
        # P1: 路径动态化 — 不再硬编码 python 绝对路径，由 load_mcp_servers_config
        # 展开 ${PYTHON_EXEC}（默认 sys.executable，保证子进程依赖一致）
        from config.settings import load_mcp_servers_config
        self.servers_config = load_mcp_servers_config()

    async def __call__(self, state: AgentState) -> Dict[str, Any]:
        config = {"configurable": {"user_id": state.get("user_id", "unknown")}}

        print("💡 [FinOpsAgent] 正在接手并分析实例监控指标，生成降本优化报告...")

        try:
            client = MultiServerMCPClient(
                connections=self.servers_config.get("mcpServers", {}),
                tool_interceptors=[UserIdInjector()]
            )
            all_tools = await client.get_tools()
            target_tools = ["query_user_instances", "analyze_instance_usage"]
            tools = [t for t in all_tools if t.name in target_tools]

            system_prompt = FINOPS_AGENT_PROMPT  # 无变量插值，直接使用常量
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
            # 非空校验：LLM 偶发返回空 content，给用户空回复体验差
            if not getattr(final_message, "content", "").strip():
                final_message = AIMessage(
                    content="抱歉，成本分析服务暂时无法返回结果，请稍后重试。"
                )
        except Exception as e:
            # 工具调用失败兜底：用 FINOPS_FALLBACK_PROMPT 让 LLM 给业务友好回复，
            # 不向用户暴露内部错误信息（异常堆栈、错误码等）
            print(f"⚠️ [FinOpsAgent] 工具调用失败，使用兜底 Prompt 回答: {str(e)}")
            try:
                response = await self.llm.ainvoke([
                    SystemMessage(content=FINOPS_FALLBACK_PROMPT)
                ])
                final_message = AIMessage(content=response.content)
            except Exception as e2:
                # 终极兜底：FALLBACK LLM 也失败（如 API Key 失效/额度耗尽），返回固定文案
                print(f"⚠️ [FinOpsAgent] 兜底 LLM 也失败，使用固定文案: {str(e2)}")
                final_message = AIMessage(
                    content="抱歉，成本分析服务当前暂时繁忙，建议您稍后重试，"
                            "或直接登录云平台控制台查看实例的 CPU、内存使用情况。"
                )

        # 执行完毕后，把 next_agent 清空，代表流程彻底结束
        return {"messages": [final_message], "next_agent": ""}

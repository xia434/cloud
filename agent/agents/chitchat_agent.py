"""ChitchatAgent - 无关问题兜底节点（OOD 路由分支）。

设计动机：
- 原 Orchestrator 兜底单一，所有无法分类的问题都路由到 product_agent，
  导致无关问题（如"今天天气怎么样"）浪费 RAG 检索 + LLM 幻觉回答。
- 新增 out_of_scope 路由分支，由 ChitchatAgent 专门承接无关问题，
  友好告知用户职责范围并引导回云产品咨询。

特点：
- 轻量节点，无工具调用，纯 LLM 直接回答
- 温度 0.7 让回复更自然友好
- 严格不回答用户当前问题，只做职责引导
"""
import os
from dotenv import load_dotenv
from langchain_core.messages import HumanMessage, SystemMessage, AIMessage

from core.workflow.state import AgentState
from typing import Dict, Any


class ChitchatAgentNode:
    """无关问题兜底节点。"""

    def __init__(self):
        dotenv_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '.env')
        load_dotenv(dotenv_path)

        # P2-10: 使用带重试机制的 LLM 工厂（替代直接 ChatOpenAI）
        # 闲聊温度 0.7 让回复更自然友好
        from core.llm_factory import create_llm_with_retry
        self.llm = create_llm_with_retry(
            model=os.getenv("MODEL", "qwen-plus"),
            api_key=os.getenv("DASHSCOPE_API_KEY"),
            base_url=os.getenv("BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1"),
            temperature=0.7,
        )

    async def __call__(self, state: AgentState) -> Dict[str, Any]:
        """供主 LangGraph 调用的处理函数。"""
        # P1-8: Prompt 抽离到 prompts/templates.py 统一管理
        from prompts.templates import CHITCHAT_PROMPT, format_memory_context

        print("💬 [ChitchatAgent] 检测到无关问题，进入 OOD 兜底分支...")

        # 取最后一条用户消息
        messages = state.get("messages", [])
        if not messages:
            last_message = ""
        else:
            last_msg_obj = messages[-1]
            if isinstance(last_msg_obj, tuple):
                last_message = last_msg_obj[1]
            elif hasattr(last_msg_obj, "content"):
                last_message = last_msg_obj.content
            else:
                last_message = str(last_msg_obj)

        # 注入记忆上下文（短期历史 + 长期偏好/事实）
        memory_context = state.get("memory_context", "")
        system_prompt = CHITCHAT_PROMPT.format(
            memory_context=format_memory_context(memory_context)
        )

        try:
            response = await self.llm.ainvoke([
                SystemMessage(content=system_prompt),
                HumanMessage(content=last_message),
            ])
            final_message = AIMessage(content=response.content)
        except Exception as e:
            # 极端兜底：LLM 调用失败时返回固定文案
            print(f"⚠️ [ChitchatAgent] LLM 调用失败，使用固定兜底文案: {str(e)}")
            final_message = AIMessage(
                content="抱歉，我是云平台客服助手，主要解答云服务器ECS、专有网络VPC、"
                        "账单查询、选型推荐、成本优化等问题。欢迎您咨询云产品相关问题～"
            )

        return {"messages": [final_message]}

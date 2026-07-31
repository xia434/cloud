import os
from typing import Dict, Any
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage, AIMessage

from core.workflow.state import AgentState

class OrchestratorAgent:
    """
    中心路由节点 (Orchestrator/Router)
    负责分析用户意图，并将请求分发给相应的专门 Agent。
    """
    def __init__(self):
        dotenv_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '.env')
        load_dotenv(dotenv_path)

        # 路由节点不需要复杂的工具，只需一个基础大模型来做分类决策
        # P2-10: 使用带重试机制的 LLM 工厂（替代直接 ChatOpenAI）
        from core.llm_factory import create_llm_with_retry
        self.llm = create_llm_with_retry(
            model=os.getenv("MODEL", "qwen-plus"),
            api_key=os.getenv("DASHSCOPE_API_KEY"),
            base_url=os.getenv("BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1"),
            temperature=0.1,
        )

    async def route(self, state: AgentState) -> Dict[str, Any]:
        """
        根据用户的最新输入，决定路由走向。

        P0 修复：增加 try-except 兜底。
        - 原问题：Orchestrator 是整个 graph 的入口节点，但无 try-except，
          LLM 调用失败（网络超时、限流、API key 失效）会导致整个 graph 崩溃，
          6 个子 Agent 的兜底机制全部失效。
        - 修复：LLM 失败时默认路由到 out_of_scope，由 ChitchatAgent 友好告知
          用户系统繁忙，避免系统级宕机。
        """
        # 获取最新的一条用户消息
        messages = state.get("messages", [])
        if not messages:
            last_message = ""
        else:
            # langgraph 内部有时候会把 tuple 转成实际的 BaseMessage 子类
            last_msg_obj = messages[-1]
            if isinstance(last_msg_obj, tuple):
                last_message = last_msg_obj[1]
            elif hasattr(last_msg_obj, "content"):
                last_message = last_msg_obj.content
            else:
                last_message = str(last_msg_obj)
        memory_context = state.get("memory_context", "")

        # P1-8: Prompt 抽离到 prompts/templates.py 统一管理
        from prompts.templates import ORCHESTRATOR_PROMPT, format_memory_context
        system_prompt = ORCHESTRATOR_PROMPT.format(
            memory_context=format_memory_context(memory_context)
        )

        # P0 修复：确保 metadata 存在，避免下标访问 KeyError
        metadata = state.get("metadata") or {}

        try:
            response = await self.llm.ainvoke([
                SystemMessage(content=system_prompt),
                HumanMessage(content=last_message)
            ])
            decision = response.content.strip().lower()
        except Exception as e:
            # LLM 调用失败兜底：路由到 out_of_scope，由 ChitchatAgent 友好告知用户
            # 不抛异常，避免整个 graph 崩溃导致 6 个子 Agent 兜底全部失效
            print(f"⚠️ [Orchestrator] LLM 调用失败，兜底路由至 out_of_scope: {str(e)}")
            metadata["is_finops_workflow"] = False
            metadata["orchestrator_error"] = str(e)[:200]
            return {"next_agent": "out_of_scope", "metadata": metadata}

        if "finops" in decision:
            next_node = "billing_agent" # FinOps 流程的第一步是交给 Billing 去查实例
            metadata["is_finops_workflow"] = True
            print("🧭 [Orchestrator] 识别到成本优化意图，触发 FinOps 工作流 (第 1 步: 获取实例数据)")
        elif "billing" in decision:
            next_node = "billing_agent"
            metadata["is_finops_workflow"] = False
            print("🧭 [Orchestrator] 识别到常规账单查询意图，路由至: billing_agent")
        elif "promotion" in decision:
            next_node = "promotion_agent"
            print("🧭 [Orchestrator] 识别到营销推广意图，路由至: promotion_agent")
        elif "recommendation" in decision:
            next_node = "recommendation_agent"
            print("🧭 [Orchestrator] 识别到选型推荐意图，路由至: recommendation_agent")
        elif "out_of_scope" in decision or "chitchat" in decision:
            next_node = "out_of_scope"
            print("🧭 [Orchestrator] 识别到无关问题（OOD），路由至: out_of_scope")
        else:
            next_node = "product_agent"
            print("🧭 [Orchestrator] 默认或识别到产品咨询意图，路由至: product_agent")

        # 返回更新后的 state
        return {"next_agent": next_node, "metadata": metadata}

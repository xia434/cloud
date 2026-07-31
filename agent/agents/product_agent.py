import os
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage, AIMessage, ToolMessage
from langgraph.prebuilt import create_react_agent

# 导入已经封装好的工具
from tools.vector_tool import query_vector_db
from tools.graph_tool import query_knowledge_graph
from core.workflow.state import AgentState
from typing import Dict, Any

class ProductAgentNode:
    """
    包装了 LangGraph create_react_agent 的节点类
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
        self.tools = [query_vector_db, query_knowledge_graph]

    async def __call__(self, state: AgentState) -> Dict[str, Any]:
        """
        供主 LangGraph 调用的处理函数
        """
        memory_context = state.get("memory_context", "")

        # P1-8: Prompt 抽离到 prompts/templates.py 统一管理
        from prompts.templates import PRODUCT_AGENT_PROMPT, PRODUCT_AGENT_FALLBACK_PROMPT, format_memory_context
        system_prompt = PRODUCT_AGENT_PROMPT.format(
            memory_context=format_memory_context(memory_context)
        )
        # 使用 create_react_agent 创建一个内部的执行器
        inner_agent = create_react_agent(
            model=self.llm,
            tools=self.tools,
            prompt=system_prompt
        )

        print("💡 [ProductAgent] 正在处理产品咨询请求...")

        try:
            last_msg = state["messages"][-1]
            user_question = last_msg[1] if isinstance(last_msg, tuple) else last_msg.content
            # 传递整个对话历史给内部 agent
            result = await inner_agent.ainvoke({"messages": state["messages"]})

            # ReAct 的第一次最终回答可能混入模型自身知识。提取真实工具证据，
            # 再做一次严格 grounded synthesis，保证最终回答可追溯。
            tool_messages = [
                message
                for message in result["messages"]
                if isinstance(message, ToolMessage)
            ]
            called_tools = {str(message.name or "") for message in tool_messages}
            tool_contexts = [
                str(message.content).strip()
                for message in tool_messages
                if _is_usable_tool_evidence(str(message.content))
            ]

            # Graph answers are precise but currently lack document provenance.
            # Add one reranked vector lookup so the final answer remains auditable.
            if (
                "query_knowledge_graph" in called_tools
                and "query_vector_db" not in called_tools
            ):
                vector_context = str(
                    await query_vector_db.ainvoke({"query": str(user_question)})
                ).strip()
                if _is_usable_tool_evidence(vector_context):
                    tool_contexts.append(vector_context)

            if tool_contexts:
                from prompts.templates import PRODUCT_GROUNDED_SYNTHESIS_PROMPT

                synthesis_prompt = PRODUCT_GROUNDED_SYNTHESIS_PROMPT.format(
                    user_question=user_question,
                    tool_context="\n\n---\n\n".join(tool_contexts),
                )
                grounded_response = await self.llm.ainvoke([
                    SystemMessage(content=synthesis_prompt),
                ])
                final_message = AIMessage(content=str(grounded_response.content).strip())
            else:
                final_message = result["messages"][-1]
        except Exception as e:
            print(f"⚠️ [ProductAgent] 工具调用失败，使用 LLM 直接回答: {str(e)}")
            # 如果工具调用失败，直接使用 LLM 回答
            last_msg = state["messages"][-1]
            user_question = last_msg[1] if isinstance(last_msg, tuple) else last_msg.content
            simplified_prompt = PRODUCT_AGENT_FALLBACK_PROMPT.format(user_question=user_question)
            try:
                response = await self.llm.ainvoke([
                    SystemMessage(content=simplified_prompt)
                ])
                content = str(response.content).strip()
                final_message = AIMessage(content=content or "知识库暂时无法返回有效结果，请稍后重试。")
            except Exception as fallback_error:
                print(f"⚠️ [ProductAgent] 兜底 LLM 也失败: {str(fallback_error)}")
                final_message = AIMessage(
                    content="抱歉，产品知识服务当前暂时不可用，请稍后重试。"
                )

        # 为了兼容主图的消息追加，我们将返回包装在 messages 列表中
        return {"messages": [final_message]}


def _is_usable_tool_evidence(content: str) -> bool:
    text = content.strip()
    if not text:
        return False
    error_markers = (
        "未在文档中检索到相关信息",
        "未查询到相关图谱信息",
        "发生错误",
        "服务不可用",
        "检索失败",
    )
    return not any(marker in text for marker in error_markers)

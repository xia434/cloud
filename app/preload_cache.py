import asyncio
import sys
import os
import glob

# 确保能正确导入 app 模块
PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
if PROJECT_DIR not in sys.path:
    sys.path.append(PROJECT_DIR)

from infra.cache import semantic_cache

# LLM 配置（从环境变量读取，用于从文档动态生成 QA）
_AGENT_DIR = os.path.join(os.path.dirname(PROJECT_DIR), "agent")
if _AGENT_DIR not in sys.path:
    sys.path.insert(0, _AGENT_DIR)

from dotenv import load_dotenv
load_dotenv(os.path.join(_AGENT_DIR, ".env"))


async def _generate_qa_from_doc(doc_path: str) -> tuple[str, str] | None:
    """用 LLM 从单个 Markdown 文档生成一条代表性 QA。

    替代原硬编码 PRESET_QA：文档更新后 QA 自动跟着变，避免缓存与知识库不一致。

    Args:
        doc_path: Markdown 文档路径

    Returns:
        (question, answer) 或 None（生成失败时）
    """
    try:
        from langchain_openai import ChatOpenAI
        from langchain_core.messages import HumanMessage, SystemMessage

        llm = ChatOpenAI(
            model=os.getenv("MODEL", "qwen-plus"),
            api_key=os.getenv("DASHSCOPE_API_KEY"),
            base_url=os.getenv("BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1"),
            temperature=0.1,
        )

        # 读取文档内容（截断到 2000 字，控制 token 成本）
        with open(doc_path, "r", encoding="utf-8") as f:
            content = f.read()[:2000]

        filename = os.path.basename(doc_path)
        prompt = f"""请基于以下文档内容，生成一个用户最可能问的高频问题，并给出文档中的标准答案。

要求：
1. 问题必须是用户视角的自然语言提问（不要出现"根据文档"等字样）
2. 答案必须严格基于文档内容，不要编造
3. 问题和答案各一行，格式如下：
QUESTION: <问题内容>
ANSWER: <答案内容>

文档文件名：{filename}
文档内容：
{content}"""

        response = await llm.ainvoke([
            SystemMessage(content="你是问答对生成助手，只输出 QUESTION 和 ANSWER 两行。"),
            HumanMessage(content=prompt),
        ])
        raw = response.content.strip()

        # 解析 QUESTION / ANSWER
        question = ""
        answer = ""
        for line in raw.split("\n"):
            line = line.strip()
            if line.upper().startswith("QUESTION:"):
                question = line[len("QUESTION:"):].strip()
            elif line.upper().startswith("ANSWER:"):
                answer = line[len("ANSWER:"):].strip()

        if question and answer:
            return (question, answer)
        return None
    except Exception as e:
        print(f"  ⚠️ 生成 QA 失败 ({doc_path}): {e}")
        return None


async def preload_cache():
    """从 mock_data 文档动态生成 QA 并预热语义缓存。

    改造说明（替代硬编码 PRESET_QA）：
    - 原实现：4 条 QA 硬编码在代码里，文档改了缓存不变，导致返回旧数据
    - 新实现：遍历 mock_data/*.md，用 LLM 从每个文档生成 1 条代表性 QA
    - 文档更新后重新跑本脚本，缓存自动更新，与知识库保持一致
    """
    print("🔄 开始预热 L1 语义缓存（从文档动态生成 QA）...")
    await semantic_cache.initialize()

    # 定位 mock_data 目录（项目根目录下）
    base_dir = os.path.dirname(os.path.dirname(PROJECT_DIR))
    mock_data_dir = os.path.join(base_dir, "mock_data")
    md_files = glob.glob(os.path.join(mock_data_dir, "*.md"))

    if not md_files:
        print(f"⚠️ 未找到 Markdown 文档: {mock_data_dir}")
        return

    print(f"📂 发现 {len(md_files)} 个文档，开始生成 QA...")
    success_count = 0
    for doc_path in md_files:
        filename = os.path.basename(doc_path)
        print(f"  处理: {filename}")
        qa = await _generate_qa_from_doc(doc_path)
        if qa:
            question, answer = qa
            print(f"    Q: {question[:50]}...")
            await semantic_cache.set_cache(question, answer)
            success_count += 1
        else:
            print(f"    ⚠️ 跳过（QA 生成失败）")

    print(f"✅ 缓存预热完成！成功注入 {success_count}/{len(md_files)} 条 QA")


if __name__ == "__main__":
    asyncio.run(preload_cache())

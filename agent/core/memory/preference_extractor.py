"""用于长期内存的基于 LLM 的用户偏好提取器。

职责：
- 使用 LLM 分析对话并提取结构化偏好
- 在返回新项之前，与已存储的偏好进行去重
- 保持无状态：调用者负责持久化

此模块有意地与 BaseAgent 和 MemoryManager 解耦，
以便它可以独立测试或替换为不同的提取器。
"""

import logging
from typing import Any

logger = logging.getLogger(__name__)

# Extraction prompt – intentionally concise to minimize token usage.
_PROMPT_TEMPLATE = """\
分析以下对话，提取两类结构化信息：

【用户偏好】（长期稳定的个人习惯、性格、语言偏好等）
格式：PREF|类别|内容
示例：PREF|城市|上海
      PREF|语言|中文
      PREF|回答风格|简洁
      PREF|性格|和善

【重要事实】（当前任务的关键上下文，可能影响后续推荐和回答）
格式：FACT|类别|内容
示例：FACT|当前任务|正在部署ECS集群做AI推理
      FACT|预算|5万元以内
      FACT|技术栈|使用PyTorch做深度学习
      FACT|历史问题|之前退款遇到过问题
      FACT|业务场景|电商大促期间的高并发

提取规则：
1. 每条单独一行，严格使用 PREF|类别|内容 或 FACT|类别|内容 格式
2. 偏好只提取长期稳定信息，不提取临时问题
3. 事实重点提取任务背景、预算、技术栈、业务场景等
4. 只提取对话中明确出现的信息，不要推测
5. 如果没有相关信息，输出: 无
6. 所有内容用中文

对话内容：
{conversation}

提取结果（或“无”）："""


class PreferenceExtractor:
    """Extracts user preferences from conversation text using an LLM.

    Args:
        llm: Any LangChain-compatible chat model (``ainvoke`` required).
        max_conversation_chars: Truncate conversation input to this length
            before sending to the LLM. Keeps token usage bounded.

    Example::

        extractor = PreferenceExtractor(llm=chat_model)
        new_prefs = await extractor.extract(
            conversation_text="user: I live in Beijing...",
            existing=["city: Shanghai"],
        )
        # new_prefs -> ["city: Beijing"]
    """

    def __init__(self, llm: Any, max_conversation_chars: int = 3000) -> None:
        self._llm = llm
        self._max_chars = max_conversation_chars

    async def extract(
        self,
        conversation_text: str,
        existing: list[str] | None = None,
    ) -> list[str]:
        """Extract new preferences from conversation text.

        Args:
            conversation_text: Raw conversation (role: content lines).
            existing: Already-stored preferences for deduplication.
                      Duplicates are silently dropped.

        Returns:
            List of new preference strings in ``"category: value"`` format.
            Empty list if nothing found or on extraction failure.
        """
        truncated = conversation_text[: self._max_chars]
        logger.debug(
            "[EXTRACTOR] Input conversation (%d chars, truncated to %d):\n%s",
            len(conversation_text), len(truncated), truncated[:400],
        )
        prompt = _PROMPT_TEMPLATE.format(conversation=truncated)

        try:
            response = await self._llm.ainvoke([{"role": "user", "content": prompt}])
            raw = response.content.strip()
            logger.debug("[EXTRACTOR] LLM raw response: %s", raw)
        except Exception as exc:
            logger.warning("PreferenceExtractor LLM call failed: %s", exc)
            return []

        if not raw or raw.strip() in ("NONE", "无", "提取结果: 无", "无相关信息"):
            logger.info("[EXTRACTOR] LLM found no preferences")
            return []

        # 解析 "PREF|类别|内容" 或 "FACT|类别|内容" 格式
        candidates = []
        for line in raw.split("\n"):
            line = line.strip()
            # 优先匹配管道符分隔的新格式
            if "|" in line and line.split("|", 1)[0].strip().upper() in ("PREF", "FACT"):
                candidates.append(line)
            # 兼容旧格式 "类别: 内容"（向后兼容）
            elif ":" in line and "|" not in line:
                candidates.append(f"PREF|{line.replace(':', '|', 1)}")
        logger.debug("[EXTRACTOR] Parsed %d candidates: %s", len(candidates), candidates)
        if not candidates:
            return []

        if not existing:
            logger.info("[EXTRACTOR] No existing prefs, keeping all %d candidates", len(candidates))
            return candidates

        # Deduplicate: skip items whose text substantially overlaps existing
        existing_lower = [e.lower() for e in existing]
        new_items: list[str] = []
        for item in candidates:
            item_lower = item.lower()
            if any(item_lower in ex or ex in item_lower for ex in existing_lower):
                logger.debug("[EXTRACTOR] Duplicate skipped: %s", item)
                continue
            new_items.append(item)

        logger.info(
            "[EXTRACTOR] Result: %d new / %d skipped(dup) / %d total candidates",
            len(new_items), len(candidates) - len(new_items), len(candidates),
        )
        return new_items

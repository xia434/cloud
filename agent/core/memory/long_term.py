"""由 Milvus 向量数据库支持的长期内存。

用户偏好和关键事实作为密集向量嵌入进行存储。
检索使用余弦相似度搜索，并按 user_id 进行过滤，因此每个用户的记忆保持隔离。
"""

import logging
from typing import Any

logger = logging.getLogger(__name__)

COLLECTION_NAME = "long_term_memory"
EMBEDDING_DIM = 1536  


class LongTermMemory:
    """用于用户偏好和事实的基于 Milvus 的长期内存。

    功能：
    - 通过 Milvus 进行密集向量搜索（余弦相似度）
    - 对 ``user_id`` 进行标量过滤，实现每用户隔离
    - 偏好助手：``save_preference(user_id, type, value)``
    - 优雅降级：如果 Milvus 不可用，操作将变为空操作

    用法::

        mem = LongTermMemory(embedding_api_key="sk-...")
        await mem.initialize()

        await mem.save_preference("user1", "language", "Chinese")
        results = await mem.retrieve_relevant("user1", "preferred language")
        await mem.close()
    """

    def __init__(
        self,
        host: str = "localhost",
        port: int = 19530,
        api_key: str | None = None,
        embedding_api_key: str | None = None,
    ) -> None:
        self._host = host
        self._port = port
        self._api_key = api_key
        self._embedding_api_key = embedding_api_key
        self._client: Any = None
        self._embeddings: Any = None
        self._available: bool = False

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def initialize(self) -> None:
        """Connect to Milvus and ensure collection exists.

        Sets _available=False on failure (no exception raised).
        """
        try:
            from pymilvus import MilvusClient  # type: ignore[import]
            from langchain_community.embeddings import DashScopeEmbeddings  # type: ignore[import]

            uri = f"http://{self._host}:{self._port}"
            connect_kwargs: dict[str, Any] = {"uri": uri}
            if self._api_key:
                connect_kwargs["token"] = self._api_key

            self._client = MilvusClient(**connect_kwargs)
            self._embeddings = DashScopeEmbeddings(
                model="text-embedding-v2",
                dashscope_api_key=self._embedding_api_key,
            )
            self._ensure_collection()
            self._available = True
            logger.info("LongTermMemory: Milvus connected at %s:%s", self._host, self._port)
        except Exception as exc:
            logger.warning(
                "LongTermMemory: Milvus unavailable (%s) – long-term memory disabled.", exc
            )
            self._available = False

    async def close(self) -> None:
        """Close Milvus client."""
        if self._client is not None:
            try:
                self._client.close()
            except Exception:
                pass

    def flush(self) -> None:
        """Force-flush inserted data so it becomes visible to subsequent queries.

        Milvus 的 insert 是异步的：数据先进 message queue，再被消费写入 segment。
        在数据未 flush 前，即使 ``consistency_level=Strong`` 的 query 也读不到。
        本方法在 background_extract 批量写入后调用一次，确保下一轮去重能读到本轮写入。
        生产环境两次调用间隔通常 > 几秒（用户输入时间），数据早 flush，影响可忽略。
        """
        if not self._available:
            return
        try:
            self._client.flush(COLLECTION_NAME)
        except Exception as exc:
            logger.warning("LongTermMemory.flush failed (non-fatal): %s", exc)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def save_memory(
        self,
        user_id: str,
        content: str,
        memory_type: str = "general",
    ) -> None:
        """Embed and store a memory entry.

        Args:
            user_id: Owner of this memory.
            content: Text to embed and store.
            memory_type: Category label (e.g. "preference", "fact").
        """
        if not self._available:
            return
        try:
            embedding = await self._embeddings.aembed_query(content)
            self._client.insert(
                collection_name=COLLECTION_NAME,
                data=[
                    {
                        "user_id": user_id,
                        "content": content,
                        "memory_type": memory_type,
                        "embedding": embedding,
                    }
                ],
            )
            logger.debug(
                "LongTermMemory: stored %s memory for user %s: %s",
                memory_type, user_id, content[:60],
            )
        except Exception as exc:
            logger.error("LongTermMemory.save_memory failed: %s", exc)

    async def save_preference(
        self, user_id: str, preference_type: str, value: str
    ) -> None:
        """Convenience wrapper for storing a user preference.

        Args:
            user_id: Owner of this preference.
            preference_type: Short label (e.g. "language", "city").
            value: Preference value (e.g. "Chinese", "Beijing").
        """
        content = f"User preference – {preference_type}: {value}"
        await self.save_memory(user_id, content, memory_type="preference")

    async def retrieve_relevant(
        self, user_id: str, query: str, top_k: int = 5, memory_type: str | None = None
    ) -> list[str]:
        """Return the top-k most relevant memory entries for a query.

        Args:
            user_id: Filter results to this user only.
            query: Natural-language query text.
            top_k: Maximum number of results to return.
            memory_type: Optional filter by memory type ("preference" or "fact").
                         None means return all types.

        Returns:
            List of content strings ordered by relevance.
        """
        if not self._available:
            return []
        try:
            query_embedding = await self._embeddings.aembed_query(query)
            # P1-8 修复：转义引号防止 Milvus filter 注入（与 cache.py 一致）
            safe_user_id = user_id.replace('"', '\\"')
            filter_expr = f'user_id == "{safe_user_id}"'
            if memory_type:
                safe_mem_type = memory_type.replace('"', '\\"')
                filter_expr += f' and memory_type == "{safe_mem_type}"'
            results = self._client.search(
                collection_name=COLLECTION_NAME,
                data=[query_embedding],
                filter=filter_expr,
                limit=top_k,
                output_fields=["content", "memory_type"],
            )
            memories: list[str] = []
            for hits in results:
                for hit in hits:
                    memories.append(hit["entity"]["content"])
            return memories
        except Exception as exc:
            logger.error("LongTermMemory.retrieve_relevant failed: %s", exc)
            return []

    async def list_all(
        self, user_id: str, memory_type: str | None = None, limit: int = 200
    ) -> list[str]:
        """Return **all** stored memory contents for a user (no semantic search).

        用 Milvus ``query`` 接口（标量过滤，非向量检索）全量列出，用于去重判断。
        与 ``retrieve_relevant`` 的区别：
        - ``retrieve_relevant``：向量相似度 top-k，按 query 召回相关条目（用于上下文注入）
        - ``list_all``：标量过滤全量返回（用于去重，必须读全部已存条目）

        Args:
            user_id: Filter results to this user only.
            memory_type: Optional filter by memory type ("preference" or "fact").
            limit: Max number of records to return (safety cap, default 200).

        Returns:
            List of content strings (may be empty if Milvus unavailable).
        """
        if not self._available:
            return []
        try:
            # P1-8 修复：转义引号防止 Milvus filter 注入（与 retrieve_relevant 一致）
            safe_user_id = user_id.replace('"', '\\"')
            filter_expr = f'user_id == "{safe_user_id}"'
            if memory_type:
                safe_mem_type = memory_type.replace('"', '\\"')
                filter_expr += f' and memory_type == "{safe_mem_type}"'
            rows = self._client.query(
                collection_name=COLLECTION_NAME,
                filter=filter_expr,
                output_fields=["content"],
                limit=limit,
                # P1-6 根因修复：去重场景必须读到全量已写入数据。
                # MilvusClient 默认 Bounded 一致性，insert 后未 flush 的数据读不到，
                # 导致同一轮 background_extract 连续调用时去重失效、重复累积。
                # Strong 一致性确保每次 query 都读到最新已写入数据。
                consistency_level="Strong",
            )
            return [row["content"] for row in rows]
        except Exception as exc:
            logger.error("LongTermMemory.list_all failed: %s", exc)
            return []

    @property
    def available(self) -> bool:
        """True if Milvus is reachable."""
        return self._available

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _ensure_collection(self) -> None:
        """Create the Milvus collection and index if they do not exist."""
        from pymilvus import DataType  # type: ignore[import]

        if self._client.has_collection(COLLECTION_NAME):
            return

        schema = self._client.create_schema()
        schema.add_field("id", DataType.INT64, is_primary=True, auto_id=True)
        schema.add_field("user_id", DataType.VARCHAR, max_length=128)
        schema.add_field("content", DataType.VARCHAR, max_length=2048)
        schema.add_field("memory_type", DataType.VARCHAR, max_length=64)
        schema.add_field("embedding", DataType.FLOAT_VECTOR, dim=EMBEDDING_DIM)

        index_params = self._client.prepare_index_params()
        index_params.add_index(
            "embedding",
            index_type="IVF_FLAT",
            metric_type="COSINE",
            params={"nlist": 128},
        )

        self._client.create_collection(
            collection_name=COLLECTION_NAME,
            schema=schema,
            index_params=index_params,
        )
        logger.info("LongTermMemory: created Milvus collection '%s'", COLLECTION_NAME)

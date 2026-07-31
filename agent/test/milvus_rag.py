import os
import sys
import argparse
from dotenv import load_dotenv
from langchain_community.document_loaders import TextLoader, DirectoryLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_community.embeddings import DashScopeEmbeddings
from langchain_milvus import Milvus
from pymilvus import connections

# ==============================================================================
# 修复 pymilvus 2.6.x 与 langchain-milvus 0.3.x 之间的兼容性问题
# (MilvusClient 连接不注册到 connections 导致的 ConnectionNotExistException)
# ==============================================================================
original_fetch = connections._fetch_handler
def patched_fetch(alias):
    try:
        return original_fetch(alias)
    except Exception:
        from pymilvus.client.connection_manager import ConnectionManager
        mgr = ConnectionManager.get_instance()
        for mc in mgr._registry.values():
            if f"cm-{id(mc.handler)}" == alias:
                return mc.handler
        for mc in mgr._dedicated.values():
            if f"cm-{id(mc.handler)}" == alias:
                return mc.handler
        raise
connections._fetch_handler = patched_fetch
# ==============================================================================

# ==============================================================================
# 环境配置加载
# ==============================================================================
dotenv_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '.env')
load_dotenv(dotenv_path)

# 获取并校验配置
api_key = os.getenv("DASHSCOPE_API_KEY")
base_url = os.getenv("BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")
milvus_host = os.getenv("MILVUS_HOST", "localhost")
milvus_port = os.getenv("MILVUS_PORT", "19530")

if not api_key:
    raise ValueError("❌ 环境变量中未找到 DASHSCOPE_API_KEY")

# 初始化 Embedding 模型 (使用 DashScope 的 text-embedding-v2)
embeddings = DashScopeEmbeddings(
    dashscope_api_key=api_key,
    model="text-embedding-v2"
)

# Milvus 连接配置
MILVUS_URI = f"http://{milvus_host}:{milvus_port}"
COLLECTION_NAME = "cloud_product_docs"

# ==============================================================================
# 核心功能类：Milvus RAG 管理器
# ==============================================================================
class MilvusRAGManager:
    def __init__(self):
        self.vector_store = None
        self._init_or_connect()

    def _init_or_connect(self):
        """连接到现有的 Milvus Collection，如果不存在则在使用时自动创建"""
        print(f"🔌 连接 Milvus 向量数据库: {MILVUS_URI}")
        
        self.vector_store = Milvus(
            embedding_function=embeddings,
            connection_args={"uri": MILVUS_URI},
            collection_name=COLLECTION_NAME,
            auto_id=True,
            drop_old=False # 默认不删除旧数据，实现增量更新
        )

    def ingest_documents(self, data_dir: str):
        """
        读取目录下的所有 Markdown 文档，分块并存入 Milvus
        """
        if not os.path.exists(data_dir):
            print(f"❌ 目录不存在: {data_dir}")
            return

        print(f"📂 正在加载目录中的 Markdown 文档: {data_dir}")
        # 1. 加载文档
        loader = DirectoryLoader(data_dir, glob="*.md", loader_cls=TextLoader, loader_kwargs={'encoding': 'utf-8'})
        documents = loader.load()
        print(f"✅ 成功加载 {len(documents)} 份文档。")

        # 2. 文本分块 (Chunking)
        # 使用递归字符拆分器，保留上下文连贯性
        text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=500,       # 向量检索的 chunk 通常比知识图谱小，以提高检索精度
            chunk_overlap=50,
            separators=["\n## ", "\n### ", "\n\n", "\n", " ", ""]
        )
        docs = text_splitter.split_documents(documents)
        print(f"🔪 文档已切分为 {len(docs)} 个 Chunk 片段。")

        # 3. 写入 Milvus (计算 Embedding 并存储)
        print(f"🧠 正在调用大模型计算向量并存入 Milvus (Collection: {COLLECTION_NAME})...")
        
        # 增量导入: 自动处理嵌入和索引建立
        Milvus.from_documents(
            docs,
            embeddings,
            connection_args={"uri": MILVUS_URI},
            collection_name=COLLECTION_NAME,
            drop_old=True # 这里我们选择覆盖旧集合以保持数据干净，如果想增量改 False
        )
        print(f"🎉 成功将 {len(docs)} 条向量数据入库！")

        # 知识库更新后必须清空语义缓存，否则用户查询会命中旧缓存返回过期答案。
        # 根因：RAG 流程是"先查语义缓存 → 命中则直接返回 → 未命中才查知识库"，
        #       如果知识库已更新但缓存未清，缓存命中的旧答案会绕过知识库检索。
        self._invalidate_semantic_cache()

    def _invalidate_semantic_cache(self):
        """知识库更新后清空语义缓存集合（qa_semantic_cache）。

        语义缓存存的是"问题→答案"的向量映射，答案是基于旧知识库生成的。
        知识库更新后这些答案已过期，必须清除，强制下次查询走 Agent 重新检索。
        """
        try:
            from pymilvus import MilvusClient
            client = MilvusClient(uri=MILVUS_URI)
            cache_collection = "qa_semantic_cache"
            if client.has_collection(cache_collection):
                # 删除集合（连同索引一起），下次写入时 cache.py 会自动重建
                client.drop_collection(cache_collection)
                print(f"🧹 已清空语义缓存集合 '{cache_collection}'，下次查询将走 Agent 重新检索")
            else:
                print(f"ℹ️ 语义缓存集合 '{cache_collection}' 不存在，无需清理")
            client.close()
        except Exception as e:
            # 清缓存失败不影响入库主流程，仅打警告
            print(f"⚠️ 清空语义缓存失败（不影响入库）: {e}")

    def query(self, question: str, top_k: int = 3):
        """
        根据用户问题，在 Milvus 中进行向量相似度检索
        """
        print(f"🔍 正在检索问题: '{question}'")

        # 执行相似度搜索
        results = self.vector_store.similarity_search_with_score(question, k=top_k)
        
        if not results:
            print("⚠️ 未找到相关的文档片段。")
            return []

        print(f"\n✅ 找到 {len(results)} 条相关片段:")
        formatted_results = []
        for i, (doc, score) in enumerate(results):
            # score 在 LangChain 的 Milvus 实现中，通常是距离（越小越相似），具体取决于 metric_type
            source = doc.metadata.get('source', 'Unknown')
            filename = os.path.basename(source)
            content = doc.page_content.strip()
            
            print(f"\n--- [片段 {i+1}] 来源: {filename} (相关度得分: {score:.4f}) ---")
            print(f"{content[:200]}...") # 打印前200个字符预览
            
            formatted_results.append({
                "content": content,
                "source": filename,
                "score": score
            })
            
        return formatted_results

# ==============================================================================
# 命令行入口：支持入库 / 查询 / 列出 三种模式
# ==============================================================================
def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="Milvus 向量 RAG 管理工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
使用示例：
  # 入库 mock_data 下所有 .md 文档
  python test/milvus_rag.py --ingest

  # 入库指定目录
  python test/milvus_rag.py --ingest --data-dir /path/to/docs

  # 查询
  python test/milvus_rag.py --query "五天无理由退款有什么限制条件"

  # 入库后查询
  python test/milvus_rag.py --ingest --query "什么是专有网络VPC"

  # 查看 collection 数据量
  python test/milvus_rag.py --list
        """,
    )
    parser.add_argument(
        "--ingest", action="store_true",
        help="入库模式：读取 mock_data 下所有 .md，切块后写入 Milvus",
    )
    parser.add_argument(
        "--data-dir",
        default=None,
        help="文档目录路径（默认：项目根目录/mock_data）",
    )
    parser.add_argument(
        "--query", type=str, default=None,
        help="查询模式：对给定问题做向量检索",
    )
    parser.add_argument(
        "--list", action="store_true",
        help="列出 cloud_product_docs collection 的数据量",
    )
    parser.add_argument(
        "--top-k", type=int, default=3,
        help="检索返回的 top-k 数量（默认 3）",
    )

    args = parser.parse_args()

    # 无参数时打印帮助
    if not (args.ingest or args.query or args.list):
        parser.print_help()
        return

    manager = MilvusRAGManager()

    # 1. 入库
    if args.ingest:
        if args.data_dir:
            data_dir = args.data_dir
        else:
            BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            data_dir = os.path.join(BASE_DIR, "mock_data")
        print(f"\n{'='*60}")
        print(f"[INGEST] 开始入库，文档目录: {data_dir}")
        print(f"{'='*60}")
        manager.ingest_documents(data_dir)

    # 2. 列出数据量
    if args.list:
        print(f"\n{'='*60}")
        print("[LIST] 查看 collection 数据量")
        print(f"{'='*60}")
        try:
            from pymilvus import MilvusClient
            client = MilvusClient(uri=MILVUS_URI)
            stats = client.get_collection_stats(COLLECTION_NAME)
            print(f"Collection: {COLLECTION_NAME}")
            print(f"数据量: {stats}")
            client.close()
        except Exception as e:
            print(f"❌ 获取数据量失败: {e}")

    # 3. 查询
    if args.query:
        print(f"\n{'='*60}")
        print(f"[QUERY] 查询: {args.query}")
        print(f"{'='*60}")
        manager.query(args.query, top_k=args.top_k)


if __name__ == "__main__":
    main()
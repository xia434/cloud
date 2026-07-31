"""验证 P1-6 / P1-8 修复效果 + 长期记忆端到端测试"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '.env'))

from core.memory.memory_manager import MemoryManager
from core.llm_factory import create_llm_with_retry


async def test():
    llm = create_llm_with_retry(
        model=os.getenv('MODEL', 'qwen-plus'),
        api_key=os.getenv('DASHSCOPE_API_KEY'),
        base_url=os.getenv('BASE_URL', 'https://dashscope.aliyuncs.com/compatible-mode/v1'),
        temperature=0.1,
    )
    memory = MemoryManager(
        redis_url=os.getenv('REDIS_URL'),
        redis_ttl=int(os.getenv('REDIS_TTL', 1800)),
        milvus_host=os.getenv('MILVUS_HOST', 'localhost'),
        milvus_port=os.getenv('MILVUS_PORT', '19530'),
        milvus_api_key=os.getenv('MILVUS_API_KEY', ''),
        embedding_api_key=os.getenv('DASHSCOPE_API_KEY'),
        summary_llm=llm,
    )
    await memory.initialize()
    print('memory available:', memory.long_term.available)

    user_id = 'test_p1_verify'
    session_id = 'sess_verify'

    # 清空旧数据
    from pymilvus import MilvusClient
    client = MilvusClient(uri='http://localhost:19530')
    try:
        client.delete(collection_name='long_term_memory', filter='user_id == "test_p1_verify"')
        print('cleared old data')
    except Exception as e:
        print('clear skip:', e)

    # P1-6 验证：先存2条偏好，再提取相同偏好，不应重复写入
    await memory.long_term.save_memory(user_id, '[城市] 上海', memory_type='preference')
    await memory.long_term.save_memory(user_id, '[回答风格] 简洁', memory_type='preference')
    print('pre-stored 2 preferences')

    # 清空 Redis 旧数据
    await memory.short_term.clear(user_id, session_id)

    # 模拟对话（包含相同的偏好 + 新的事实）
    messages = [
        {'role': 'user', 'content': '我在上海，希望回答简洁'},
        {'role': 'assistant', 'content': '好的，我会用简洁的方式回答您。请问有什么可以帮您？'},
        {'role': 'user', 'content': '我需要部署ECS集群做AI推理，预算5万'},
        {'role': 'assistant', 'content': '推荐gn7i GPU实例，适合AI推理场景。'},
    ]
    await memory.short_term.save_messages(user_id, session_id, messages)

    # 调用 background_extract
    result = await memory.background_extract(user_id, session_id, llm=llm)
    print(f'background_extract returned {len(result) if result else 0} items')
    print(f'extracted: {result}')

    # 检查 Milvus 里的数据（用 Strong 一致性，确保读到刚 flush 的数据）
    rows = client.query(
        collection_name='long_term_memory',
        filter='user_id == "test_p1_verify"',
        output_fields=['content', 'memory_type'],
        limit=20,
        consistency_level='Strong',
    )
    print(f'\nMilvus total records: {len(rows)}')
    for r in rows:
        print(f'  [{r["memory_type"]}] {r["content"]}')

    # P1-6 核心验证：城市上海不应重复
    city_count = sum(1 for r in rows if '上海' in r['content'] and '城市' in r['content'])
    print(f'\n[P1-6] 城市上海记录数: {city_count} (应为1，>1说明去重失败)')

    # 再次 extract（模拟第二次调用，验证不会无限累积）
    result2 = await memory.background_extract(user_id, session_id, llm=llm)
    print(f'第二次 extract 返回 {len(result2) if result2 else 0} items（应为0）')
    rows2 = client.query(
        collection_name='long_term_memory',
        filter='user_id == "test_p1_verify"',
        output_fields=['content', 'memory_type'],
        limit=20,
        consistency_level='Strong',
    )
    print(f'第二次 extract 后 Milvus 总记录数: {len(rows2)} (应与第一次相同)')
    p16_ok = len(rows2) == len(rows)
    print(f'[P1-6] 重复extract后是否累积: {"是(bug)" if len(rows2) > len(rows) else "否(正常)"}')

    # P1-8 验证：带引号的 user_id 不应崩溃
    print('\n[P1-8] 测试带引号的 user_id...')
    try:
        await memory.long_term.retrieve_relevant(user_id='test"inject', query='测试')
        print('[P1-8] 带引号 user_id 未崩溃: 通过')
        p18_ok = True
    except Exception as e:
        print(f'[P1-8] 带引号 user_id 崩溃: 失败 - {e}')
        p18_ok = False

    client.close()
    await memory.short_term.clear(user_id, session_id)

    print('\n' + '=' * 50)
    print(f'P1-6 (去重格式修复): {"通过" if p16_ok else "失败"}')
    print(f'P1-8 (引号转义修复): {"通过" if p18_ok else "失败"}')
    print('=' * 50)


if __name__ == '__main__':
    asyncio.run(test())

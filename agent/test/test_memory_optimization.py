"""短期记忆摘要压缩 + 长期记忆双类型提取 集成测试脚本。

验证两个优化：
1. 短期记忆超过 12 条时，较早消息被 LLM 压缩成摘要（不直接丢弃）
2. 长期记忆提取的偏好和事实分别以 "preference" / "fact" 类型存入 Milvus

运行方式：
    cd d:\deep_research\deep_research\cloud_agent\agent
    D:\python312\python.exe test\test_memory_optimization.py
"""
import asyncio
import sys
import os
import json

# 加载环境变量
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '.env'))

# 加载 app 路径
APP_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '..', 'app')
sys.path.insert(0, APP_DIR)


async def test_short_term_compression():
    """测试1：短期记忆摘要压缩"""
    print("\n" + "=" * 70)
    print("测试1：短期记忆摘要压缩（超过12条触发 LLM 摘要）")
    print("=" * 70)

    from core.memory.short_term import ShortTermMemory
    from core.llm_factory import create_llm_with_retry

    # 创建带 LLM 的 ShortTermMemory
    llm = create_llm_with_retry(
        model=os.getenv("MODEL", "qwen-plus"),
        api_key=os.getenv("DASHSCOPE_API_KEY"),
        base_url=os.getenv("BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1"),
        temperature=0,
    )

    redis_url = os.getenv("REDIS_URL", "redis://localhost:6379")
    mem = ShortTermMemory(redis_url=redis_url, ttl=600, llm=llm)
    await mem.initialize()

    if not mem.available:
        print("❌ Redis 不可用，跳过测试")
        return False

    user_id = "test_compress_user"
    session_id = "test_compress_session"

    # 清理旧数据
    await mem.clear(user_id, session_id)

    # 构造 14 条消息（超过 COMPRESSION_THRESHOLD=12）
    print("\n📋 构造 14 条对话消息（超过阈值12，应触发压缩）...")
    messages = [
        {"role": "user", "content": "我是做AI深度学习的，需要GPU实例"},
        {"role": "assistant", "content": "推荐您使用 gn7i 系列，搭载 NVIDIA A10 GPU..."},
        {"role": "user", "content": "预算大概5万以内"},
        {"role": "assistant", "content": "gn7i.xlarge 符合您的预算，月费约4500元..."},
        {"role": "user", "content": "用什么深度学习框架好？"},
        {"role": "assistant", "content": "推荐 PyTorch，生态完善，GPU加速支持好..."},
        {"role": "user", "content": "数据集大概500GB"},
        {"role": "assistant", "content": "建议挂载 ESSD PL2 云盘，IOPS 能满足训练需求..."},
        {"role": "user", "content": "训练时会遇到CUDA内存不足吗？"},
        {"role": "assistant", "content": "gn7i.xlarge 有24GB显存，对中等模型够用..."},
        {"role": "user", "content": "需要配置Docker环境吗？"},
        {"role": "assistant", "content": "建议用Docker，方便管理PyTorch版本和依赖..."},
        {"role": "user", "content": "第7轮问题：监控怎么配"},
        {"role": "assistant", "content": "第7轮回答：用云监控服务，关注GPU利用率指标..."},
        {"role": "user", "content": "第8轮问题：日志收集方案"},
        {"role": "assistant", "content": "第8轮回答：推荐用ELK或Loki+Grafana..."},
    ]

    print(f"   原始消息数: {len(messages)}")

    # 保存（应触发压缩）
    print("\n💾 保存到 Redis（应触发摘要压缩）...")
    await mem.save_messages(user_id, session_id, messages)

    # 读回验证
    stored = await mem.get_messages(user_id, session_id)
    print(f"   压缩后存储的消息数: {len(stored)}")

    # 检查是否有摘要 system 消息
    has_summary = any(
        m.get("role") == "system" and "历史对话摘要" in m.get("content", "")
        for m in stored
    )

    if has_summary:
        print("\n✅ 优化1验证通过：检测到 [历史对话摘要] system 消息")
        # 打印摘要内容
        for m in stored:
            if m.get("role") == "system":
                print(f"\n   摘要内容: {m['content']}")
                break
        # 打印保留的最近消息
        recent_msgs = [m for m in stored if m.get("role") != "system"]
        print(f"\n   保留的最近消息数: {len(recent_msgs)}")
        print(f"   最近一条: {recent_msgs[-1]['content'] if recent_msgs else '无'}")

        # 关键验证：摘要里是否包含早期关键信息
        summary_content = next(
            (m["content"] for m in stored if m.get("role") == "system"), ""
        )
        keywords = ["AI", "深度学习", "GPU", "gn7i", "5万", "PyTorch"]
        preserved = [k for k in keywords if k in summary_content]
        print(f"\n   摘要保留的关键信息: {preserved}")
        if len(preserved) >= 4:
            print("   ✅ 摘要成功保留了早期对话的关键信息（不会丢失上下文）")
        else:
            print(f"   ⚠️ 摘要保留的关键信息较少（{len(preserved)}/{len(keywords)}）")
    else:
        print("\n❌ 优化1验证失败：未检测到摘要消息")
        print("   存储的消息:")
        for m in stored:
            print(f"   - [{m['role']}] {m['content'][:50]}")

    # 清理
    await mem.clear(user_id, session_id)
    await mem.close()
    return has_summary


async def test_long_term_dual_type():
    """测试2：长期记忆双类型提取（偏好+事实）"""
    print("\n" + "=" * 70)
    print("测试2：长期记忆双类型提取（PREF + FACT）")
    print("=" * 70)

    from core.memory.preference_extractor import PreferenceExtractor
    from core.llm_factory import create_llm_with_retry

    llm = create_llm_with_retry(
        model=os.getenv("MODEL", "qwen-plus"),
        api_key=os.getenv("DASHSCOPE_API_KEY"),
        base_url=os.getenv("BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1"),
        temperature=0.1,
    )

    extractor = PreferenceExtractor(llm=llm)

    # 模拟一段包含偏好和事实的对话
    conversation = """user: 我是做AI深度学习的，需要GPU实例
assistant: 推荐您使用 gn7i 系列
user: 预算大概5万以内，用PyTorch训练
assistant: gn7i.xlarge 符合预算，适合PyTorch
user: 我在上海，喜欢简洁的回答
assistant: 好的，记住了您的偏好"""

    print(f"\n📋 模拟对话内容:\n{conversation}")

    print("\n🧠 调用 PreferenceExtractor 提取（应返回 PREF 和 FACT 两类）...")
    new_items = await extractor.extract(conversation_text=conversation, existing=None)

    print(f"\n   提取结果（{len(new_items)} 条）:")
    pref_count = 0
    fact_count = 0
    for item in new_items:
        print(f"   - {item}")
        if item.startswith("PREF|"):
            pref_count += 1
        elif item.startswith("FACT|"):
            fact_count += 1

    print(f"\n   偏好(PREF): {pref_count} 条")
    print(f"   事实(FACT): {fact_count} 条")

    success = pref_count > 0 and fact_count > 0
    if success:
        print("\n✅ 优化2验证通过：成功提取出偏好和事实两类记忆")

        # 进一步验证解析逻辑
        print("\n🔧 验证 _parse_memory_item 解析逻辑...")
        from core.memory.memory_manager import MemoryManager
        for item in new_items:
            parsed = MemoryManager._parse_memory_item(item)
            if parsed:
                mem_type, category, content = parsed
                print(f"   {item} → type={mem_type}, category={category}, content={content}")
            else:
                print(f"   ❌ 解析失败: {item}")
    else:
        print(f"\n❌ 优化2验证失败：偏好={pref_count}, 事实={fact_count}")
        print("   期望：两类都 > 0")

    return success


async def test_milvus_dual_type_storage():
    """测试3：双类型记忆实际写入 Milvus 并按类型检索"""
    print("\n" + "=" * 70)
    print("测试3：双类型记忆写入 Milvus + 按类型检索")
    print("=" * 70)

    from core.memory.long_term import LongTermMemory

    mem = LongTermMemory(
        host=os.getenv("MILVUS_HOST", "localhost"),
        port=int(os.getenv("MILVUS_PORT", "19530")),
        embedding_api_key=os.getenv("DASHSCOPE_API_KEY"),
    )
    await mem.initialize()

    if not mem.available:
        print("❌ Milvus 不可用，跳过测试")
        return False

    test_user = "test_dual_type_user"

    # 清理旧数据（通过检索看是否有残留）
    print(f"\n🧹 检查用户 {test_user} 的旧数据...")
    old_data = await mem.retrieve_relevant(test_user, "测试", top_k=20)
    if old_data:
        print(f"   发现 {len(old_data)} 条旧数据（不影响测试）")

    # 写入两条测试数据：一条偏好，一条事实
    print("\n💾 写入测试数据...")
    await mem.save_memory(test_user, "[城市] 上海", memory_type="preference")
    await mem.save_memory(test_user, "[回答风格] 简洁", memory_type="preference")
    await mem.save_memory(test_user, "[当前任务] 部署ECS集群做AI推理", memory_type="fact")
    await mem.save_memory(test_user, "[预算] 5万元以内", memory_type="fact")
    print("   写入: 2条偏好 + 2条事实")

    # 等一下让索引刷新
    await asyncio.sleep(1)

    # 按类型检索验证
    print("\n🔍 按类型检索验证...")

    # 检索偏好
    prefs = await mem.retrieve_relevant(test_user, "用户偏好城市风格", top_k=5, memory_type="preference")
    print(f"   检索 preference: {len(prefs)} 条 → {prefs}")

    # 检索事实
    facts = await mem.retrieve_relevant(test_user, "任务预算部署", top_k=5, memory_type="fact")
    print(f"   检索 fact: {len(facts)} 条 → {facts}")

    # 验证类型隔离
    pref_has_fact = any("部署" in p or "预算" in p for p in prefs)
    fact_has_pref = any("城市" in f or "风格" in f for f in facts)

    success = len(prefs) > 0 and len(facts) > 0 and not pref_has_fact and not fact_has_pref
    if success:
        print("\n✅ 优化2存储验证通过：")
        print("   - preference 类型只返回偏好数据")
        print("   - fact 类型只返回事实数据")
        print("   - 类型隔离正确")
    else:
        print("\n❌ 优化2存储验证失败：类型隔离异常")
        print(f"   偏好里混入事实: {pref_has_fact}")
        print(f"   事实里混入偏好: {fact_has_pref}")

    await mem.close()
    return success


async def main():
    print("=" * 70)
    print("记忆系统优化集成测试")
    print("优化1: 短期记忆摘要压缩")
    print("优化2: 长期记忆偏好+事实双类型")
    print("=" * 70)

    results = {}

    # 测试1：短期记忆摘要压缩
    try:
        results["short_term_compression"] = await test_short_term_compression()
    except Exception as e:
        print(f"\n❌ 测试1异常: {e}")
        import traceback
        traceback.print_exc()
        results["short_term_compression"] = False

    # 测试2：长期记忆双类型提取
    try:
        results["long_term_dual_type_extract"] = await test_long_term_dual_type()
    except Exception as e:
        print(f"\n❌ 测试2异常: {e}")
        import traceback
        traceback.print_exc()
        results["long_term_dual_type_extract"] = False

    # 测试3：Milvus 双类型存储+检索
    try:
        results["milvus_dual_type_storage"] = await test_milvus_dual_type_storage()
    except Exception as e:
        print(f"\n❌ 测试3异常: {e}")
        import traceback
        traceback.print_exc()
        results["milvus_dual_type_storage"] = False

    # 汇总
    print("\n" + "=" * 70)
    print("测试结果汇总")
    print("=" * 70)
    for name, passed in results.items():
        status = "✅ 通过" if passed else "❌ 失败"
        print(f"  {name}: {status}")

    all_passed = all(results.values())
    print(f"\n{'🎉 全部测试通过！优化已达到预期效果' if all_passed else '⚠️ 部分测试未通过，请检查'}")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(main())

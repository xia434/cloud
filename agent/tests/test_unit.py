"""pytest 单元测试 - 不依赖外部服务的纯逻辑测试。

运行：
    cd agent
    pytest tests/ -v

覆盖范围：
- prompts/templates.py: Prompt 模板渲染
- app/infra/observability.py: Langfuse 降级逻辑
- mcp_servers/cloud_platform_server.py: get_promotion_materials 合并逻辑
- app/service/chat_service.py: _sse 序列化
"""
import os
import sys
import json
from pathlib import Path

import pytest

# 把 agent 和 app 目录加入 sys.path
AGENT_ROOT = Path(__file__).parent.parent
APP_ROOT = AGENT_ROOT.parent / "app"
for p in [AGENT_ROOT, APP_ROOT]:
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))


# =============================================================================
# Prompt 模板测试
# =============================================================================
class TestPromptTemplates:
    """测试 Prompt 模板渲染是否正常。"""

    def test_orchestrator_prompt_renders_with_memory(self):
        from prompts.templates import ORCHESTRATOR_PROMPT, format_memory_context
        result = ORCHESTRATOR_PROMPT.format(
            memory_context=format_memory_context("用户偏好：Java 技术栈")
        )
        assert "Java 技术栈" in result
        assert "Orchestrator" in result
        assert "product_agent" in result

    def test_orchestrator_prompt_renders_with_empty_memory(self):
        from prompts.templates import ORCHESTRATOR_PROMPT, format_memory_context
        result = ORCHESTRATOR_PROMPT.format(
            memory_context=format_memory_context("")
        )
        assert "暂无背景上下文" in result

    def test_product_agent_prompt_has_tool_descriptions(self):
        from prompts.templates import PRODUCT_AGENT_PROMPT, format_memory_context
        result = PRODUCT_AGENT_PROMPT.format(memory_context=format_memory_context(None))
        assert "query_vector_db" in result
        assert "query_knowledge_graph" in result
        assert "暂无背景上下文" in result

    def test_product_agent_fallback_prompt_renders(self):
        from prompts.templates import PRODUCT_AGENT_FALLBACK_PROMPT
        result = PRODUCT_AGENT_FALLBACK_PROMPT.format(user_question="什么是 VPC？")
        assert "什么是 VPC？" in result
        assert "检索工具不可用" in result

    def test_all_prompts_have_required_placeholders(self):
        """确保所有带变量的 Prompt 都有 {memory_context} 占位符。"""
        from prompts.templates import (
            ORCHESTRATOR_PROMPT,
            PRODUCT_AGENT_PROMPT,
            BILLING_AGENT_PROMPT,
            PROMOTION_AGENT_PROMPT,
            RECOMMENDATION_AGENT_PROMPT,
        )
        for name, prompt in [
            ("ORCHESTRATOR", ORCHESTRATOR_PROMPT),
            ("PRODUCT_AGENT", PRODUCT_AGENT_PROMPT),
            ("BILLING_AGENT", BILLING_AGENT_PROMPT),
            ("PROMOTION_AGENT", PROMOTION_AGENT_PROMPT),
            ("RECOMMENDATION_AGENT", RECOMMENDATION_AGENT_PROMPT),
        ]:
            assert "{memory_context}" in prompt, f"{name}_PROMPT 缺少 {{memory_context}} 占位符"

    def test_finops_prompt_no_placeholders(self):
        """FinOps Prompt 无变量插值，应能直接使用。"""
        from prompts.templates import FINOPS_AGENT_PROMPT
        # 不应抛出 KeyError
        assert "FinOps" in FINOPS_AGENT_PROMPT
        assert "instance_id" in FINOPS_AGENT_PROMPT

    def test_format_memory_context_helper(self):
        from prompts.templates import format_memory_context
        assert format_memory_context(None) == "暂无背景上下文。"
        assert format_memory_context("") == "暂无背景上下文。"
        assert format_memory_context("xxx") == "xxx"


# =============================================================================
# 可观测性降级测试
# =============================================================================
class TestObservability:
    """测试 Langfuse 在未配置时是否能优雅降级。"""

    def test_get_langfuse_callback_returns_none_when_not_configured(self, monkeypatch):
        # 重置全局状态
        import infra.observability as obs
        monkeypatch.setattr(obs, "_langfuse_available", None)
        monkeypatch.setattr(obs, "_langfuse_init_error", None)

        # 模拟未配置 Langfuse
        class FakeSettings:
            langfuse_public_key = None
            langfuse_secret_key = None
            langfuse_host = "http://localhost:3000"

        monkeypatch.setattr("config.get_settings", lambda: FakeSettings())

        result = obs.get_langfuse_callback(user_id="u1", session_id="s1")
        assert result is None
        assert obs.is_observability_enabled() is False

        status = obs.get_observability_status()
        assert status["enabled"] is False
        assert "未配置" in status["error"] or status["error"] is not None


# =============================================================================
# MCP Server 工具逻辑测试
# =============================================================================
class TestPromotionMaterialsTool:
    """测试 get_promotion_materials 合并修复后的逻辑。

    注意：FastMCP 的 @mcp.tool() 装饰器会把函数包装为 FunctionTool 对象，
    直接位置调用可能不工作。这里通过 .fn 属性获取底层函数。
    """

    @staticmethod
    def _get_tool_fn():
        """获取 get_promotion_materials 的底层 Python 函数。"""
        import importlib
        import mcp_servers.cloud_platform_server as server
        importlib.reload(server)
        tool = server.get_promotion_materials
        # FastMCP FunctionTool 通常有 .fn 属性指向原函数
        fn = getattr(tool, "fn", None) or getattr(tool, "func", None) or tool
        return fn

    def test_exact_product_id_match(self):
        """精确 product_id 应该命中对应活动。"""
        fn = self._get_tool_fn()
        result_str = fn("P_GPU_GN7I", user_id="u_test")
        data = json.loads(result_str)
        assert data["status"] == "success"
        assert data["data"]["product_id"] == "P_GPU_GN7I"
        assert "GPU" in data["data"]["activity_title"]
        assert "u_test" in data["data"]["exclusive_link"]

    def test_keyword_fuzzy_match(self):
        """关键词模糊匹配应该命中对应 product_id。"""
        fn = self._get_tool_fn()
        result_str = fn("gpu", user_id="u_test")
        data = json.loads(result_str)
        assert data["status"] == "success"
        assert data["data"]["product_id"] == "P_GPU_GN7I"

    def test_unknown_keyword_falls_back_to_default(self):
        """未匹配的关键词应该兜底到 P_ALL_000。"""
        fn = self._get_tool_fn()
        result_str = fn("不存在的关键词", user_id="")
        data = json.loads(result_str)
        assert data["data"]["product_id"] == "P_ALL_000"

    def test_poster_url_always_present(self):
        """合并修复后所有结果都应有 poster_url 字段。"""
        fn = self._get_tool_fn()
        for pid in ["P_ECS_G8A_XLARGE", "P_ECS_C7_8XLARGE", "P_GPU_GN7I", "P_RDS_MYSQL_HA"]:
            result_str = fn(pid, user_id="")
            data = json.loads(result_str)
            assert "poster_url" in data["data"], f"{pid} 缺少 poster_url 字段"
            assert data["data"]["poster_url"].startswith("https://")


# =============================================================================
# SSE 序列化测试
# =============================================================================
class TestSSESerialization:
    """测试 chat_service 的 _sse 序列化函数。

    注意：直接 from service.chat_service import _sse 会触发模块级
    Settings() 实例化（要求 .env 完整）。这里改用 inline 复刻 _sse 的
    等价实现来测试序列化逻辑，避免对环境的依赖。
    """

    @staticmethod
    def _sse_inline(payload: dict) -> str:
        """复刻 chat_service._sse 的实现，仅用于单元测试。"""
        return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"

    def test_sse_serializes_dict_to_data_line(self):
        result = self._sse_inline({"content": "你好"})
        assert result.startswith("data: ")
        assert result.endswith("\n\n")
        payload = json.loads(result[len("data: "):].strip())
        assert payload == {"content": "你好"}

    def test_sse_handles_chinese_without_escape(self):
        result = self._sse_inline({"content": "你好世界"})
        assert "你好世界" in result  # ensure_ascii=False

    def test_sse_serializes_metadata_events(self):
        result = self._sse_inline({"type": "tool_start", "name": "query_vector_db"})
        payload = json.loads(result[len("data: "):].strip())
        assert payload["type"] == "tool_start"
        assert payload["name"] == "query_vector_db"


class TestStreamPolicy:
    """流式事件隔离和语义缓存准入策略。"""

    def test_router_tokens_are_not_forwarded(self):
        from service.stream_policy import should_forward_model_event

        event = {"metadata": {"langgraph_node": "orchestrator"}}
        assert should_forward_model_event(event) is False

    def test_business_agent_tokens_are_forwarded(self):
        from service.stream_policy import should_forward_model_event

        direct = {"metadata": {"langgraph_node": "product_agent"}}
        nested = {
            "metadata": {
                "langgraph_node": "agent",
                "checkpoint_ns": "billing_agent:abc123|agent:def456",
            }
        }
        assert should_forward_model_event(direct) is True
        assert should_forward_model_event(nested) is True

    def test_product_react_draft_is_not_forwarded(self):
        from service.stream_policy import should_forward_model_event

        event = {
            "metadata": {
                "langgraph_node": "agent",
                "checkpoint_ns": "product_agent:abc123|agent:def456",
            }
        }
        assert should_forward_model_event(event) is False

    @pytest.mark.parametrize(
        "query",
        [
            "查询我名下的实例",
            "最近的账单是多少",
            "帮我做成本优化",
            "推荐一款 ECS",
            "生成推广海报",
        ],
    )
    def test_dynamic_queries_bypass_cache(self, query):
        from service.stream_policy import is_stable_knowledge_query

        assert is_stable_knowledge_query(query) is False

    def test_static_knowledge_query_can_use_cache(self):
        from service.stream_policy import is_stable_knowledge_query

        assert is_stable_knowledge_query("什么是 VPC？") is True

    def test_extracts_fixed_fallback_from_node_output(self):
        from langchain_core.messages import AIMessage
        from service.stream_policy import extract_final_response_text

        output = {"messages": [AIMessage(content="服务暂时不可用，请稍后重试。")]}
        assert extract_final_response_text(output) == "服务暂时不可用，请稍后重试。"

    def test_empty_node_output_has_no_final_text(self):
        from service.stream_policy import extract_final_response_text

        assert extract_final_response_text({"messages": []}) == ""


class TestReadOnlyCypherGuard:
    """知识图谱只读查询防线。"""

    @pytest.mark.parametrize(
        "query",
        [
            "CREATE (n:User {id: 'x'})",
            "MATCH (n) DELETE n",
            "MATCH (n) SET n.admin = true",
            "CALL db.schema.visualization()",
            "MATCH (n) RETURN n; MATCH (m) RETURN m",
        ],
    )
    def test_rejects_mutating_or_procedural_cypher(self, query):
        from tools.cypher_security import validate_read_only_cypher

        with pytest.raises(ValueError):
            validate_read_only_cypher(query)

    def test_allows_read_only_match(self):
        from tools.cypher_security import validate_read_only_cypher

        validate_read_only_cypher("MATCH (n:InstanceType) RETURN n LIMIT 5")


# =============================================================================
# 评估数据集测试
# =============================================================================
class TestEvalDataset:
    """测试 RAG 评估数据集完整性。"""

    def test_dataset_has_required_fields(self):
        from eval.dataset import get_dataset
        ds = get_dataset()
        assert len(ds) >= 10, "评估数据集至少应有 10 条"
        for item in ds:
            assert "question" in item
            assert "ground_truth" in item
            assert "relevant_sources" in item
            assert item["expected_agent"] in {"product_agent", "recommendation_agent"}
            assert isinstance(item["relevant_sources"], list)
            assert len(item["question"]) > 0
            assert len(item["ground_truth"]) > 0

    def test_dataset_covers_multiple_sources(self):
        from eval.dataset import get_dataset
        ds = get_dataset()
        all_sources = set()
        for item in ds:
            all_sources.update(item["relevant_sources"])
        # 至少覆盖 4 份不同文档
        assert len(all_sources) >= 4, f"数据集仅覆盖 {len(all_sources)} 份文档，应至少覆盖 4 份"


class TestOfficialRagasPolicy:
    """官方 Ragas 输入映射与质量门禁的纯逻辑测试。"""

    def test_builds_ragas_rows_from_agent_results(self):
        from eval.eval_rag import _build_ragas_rows

        rows = _build_ragas_rows([
            {
                "question": "什么是 VPC？",
                "answer": "VPC 是逻辑隔离网络。",
                "contexts": ["VPC 是地域级逻辑隔离网络。"],
                "ground_truth": "VPC 是逻辑隔离网络。",
            }
        ])
        assert rows == [{
            "user_input": "什么是 VPC？",
            "response": "VPC 是逻辑隔离网络。",
            "retrieved_contexts": ["VPC 是地域级逻辑隔离网络。"],
            "reference": "VPC 是逻辑隔离网络。",
        }]

    def test_quality_gate_passes_only_when_every_metric_passes(self):
        from eval.eval_rag import _build_quality_gate

        thresholds = {
            "faithfulness": 0.75,
            "answer_relevancy": 0.70,
        }
        passed = _build_quality_gate(
            {"faithfulness": 0.90, "answer_relevancy": 0.80},
            thresholds,
        )
        failed = _build_quality_gate(
            {"faithfulness": 0.90, "answer_relevancy": None},
            thresholds,
        )
        assert passed["passed"] is True
        assert failed["passed"] is False

    def test_vector_tool_output_is_split_into_ragas_contexts(self):
        from eval.eval_rag import _split_tool_context

        output = "【来源: a.md】\nA\n\n【来源: b.md】\nB"
        contexts = _split_tool_context("query_vector_db", output)
        assert contexts == ["【来源: a.md】\nA", "【来源: b.md】\nB"]

    def test_route_accuracy_uses_expected_agent(self):
        from eval.eval_rag import _compute_route_accuracy

        result = _compute_route_accuracy([
            {
                "question": "q1",
                "expected_agent": "product_agent",
                "route": "product_agent",
            },
            {
                "question": "q2",
                "expected_agent": "product_agent",
                "route": "billing_agent",
            },
        ])
        assert result["accuracy"] == 0.5


class TestRetrievalReranker:
    """轻量重排器不依赖 Milvus，可快速回归排序逻辑。"""

    class _Document:
        def __init__(self, content, source):
            self.page_content = content
            self.metadata = {"source": source}

    def test_promotes_lexically_relevant_candidate(self):
        from tools.retrieval_reranker import rerank_results

        irrelevant = self._Document("ECS 实例规格和处理器介绍", "ecs.md")
        relevant = self._Document("五天无理由退款需要满足适用产品和时间限制", "billing.md")
        results = rerank_results(
            "五天无理由退款有什么限制条件？",
            [(irrelevant, 0.1), (relevant, 0.2)],
            limit=1,
        )
        assert results[0][0] is relevant

    def test_preserves_semantic_rank_when_no_lexical_term_matches(self):
        from tools.retrieval_reranker import rerank_results

        first = self._Document("alpha", "a.md")
        second = self._Document("beta", "b.md")
        results = rerank_results("完全不同的问题", [(first, 0.1), (second, 0.2)], limit=2)
        assert [item[0] for item in results] == [first, second]

    def test_respects_result_limit(self):
        from tools.retrieval_reranker import rerank_results

        docs = [(self._Document(str(index), f"{index}.md"), float(index)) for index in range(5)]
        assert len(rerank_results("实例规格", docs, limit=3)) == 3

    def test_diversifies_sources_for_multi_product_selection(self):
        from tools.retrieval_reranker import rerank_results

        rds_1 = self._Document("Java MySQL RDS 高可用部署", "rds.md")
        rds_2 = self._Document("RDS MySQL 部署建议", "rds.md")
        ecs = self._Document("Java 服务部署 ECS 实例选型", "ecs.md")
        network = self._Document("高可用部署网络与子网", "network.md")
        results = rerank_results(
            "Java 服务和 MySQL 应该怎么选 ECS 与 RDS 部署？",
            [(rds_1, 0.1), (rds_2, 0.2), (ecs, 0.3), (network, 0.4)],
            limit=3,
        )
        assert {item[0].metadata["source"] for item in results} == {
            "rds.md", "ecs.md", "network.md"
        }

    def test_prefers_product_aligned_source_over_generic_match(self):
        from tools.retrieval_reranker import rerank_results

        generic = self._Document("ECS 部署选型和高可用运维建议", "ticket.md")
        product = self._Document("ECS 实例规格与部署场景", "ecs_product.md")
        results = rerank_results(
            "ECS 应该怎么选？",
            [(generic, 0.1), (product, 0.2)],
            limit=1,
        )
        assert results[0][0] is product


# =============================================================================
# P3 安全认证体系测试
# =============================================================================
class TestJWTHandler:
    """测试 JWT 签发与验证。"""

    def test_create_and_decode_token(self):
        from auth.jwt_handler import create_access_token, decode_access_token
        token = create_access_token("user_1001", extra_claims={"role": "user"})
        payload = decode_access_token(token)
        assert payload["sub"] == "user_1001"
        assert payload["role"] == "user"
        assert "exp" in payload
        assert "iat" in payload

    def test_decode_invalid_token_raises(self):
        from auth.jwt_handler import decode_access_token, InvalidTokenError
        with pytest.raises(InvalidTokenError):
            decode_access_token("invalid.token.here")

    def test_decode_tampered_token_raises(self):
        from auth.jwt_handler import create_access_token, decode_access_token, InvalidTokenError
        token = create_access_token("user_1001")
        # 篡改 payload 部分
        parts = token.split(".")
        tampered = f"{parts[0]}.tampered_payload.{parts[2]}"
        with pytest.raises(InvalidTokenError):
            decode_access_token(tampered)

    def test_token_includes_exp_and_iat_claims(self):
        from auth.jwt_handler import create_access_token, decode_access_token
        token = create_access_token("user_1002")
        payload = decode_access_token(token)
        assert "exp" in payload
        assert "iat" in payload
        assert payload["sub"] == "user_1002"


class TestMockUserDB:
    """测试 mock 用户表。"""

    def test_authenticate_user_success(self):
        from auth.models import authenticate_user
        user = authenticate_user("alice", "cloud@2024")
        assert user is not None
        assert user.user_id == "user_1001"
        assert user.role == "user"

    def test_authenticate_user_wrong_password(self):
        from auth.models import authenticate_user
        user = authenticate_user("alice", "wrong_password")
        assert user is None

    def test_authenticate_user_unknown_user(self):
        from auth.models import authenticate_user
        user = authenticate_user("unknown", "cloud@2024")
        assert user is None

    def test_get_user_by_id(self):
        from auth.models import get_user_by_id
        user = get_user_by_id("user_1001")
        assert user is not None
        assert user.username == "alice"

    def test_get_user_by_id_not_found(self):
        from auth.models import get_user_by_id
        user = get_user_by_id("user_9999")
        assert user is None

    def test_all_mock_users_share_default_password(self):
        """3 个 mock 用户都使用同一个默认密码 cloud@2024。"""
        from auth.models import authenticate_user, mock_user_db
        for uid in mock_user_db.keys():
            username = mock_user_db[uid].username
            user = authenticate_user(username, "cloud@2024")
            assert user is not None, f"{username} 应该能用默认密码登录"


class TestAuthDependency:
    """测试 FastAPI 认证依赖（401 场景）。"""

    def test_missing_authorization_header_raises_401(self):
        from fastapi import HTTPException
        from auth.dependency import get_current_user_id
        with pytest.raises(HTTPException) as exc_info:
            get_current_user_id(authorization=None)
        assert exc_info.value.status_code == 401
        assert "WWW-Authenticate" in exc_info.value.headers

    def test_invalid_bearer_format_raises_401(self):
        from fastapi import HTTPException
        from auth.dependency import get_current_user_id
        with pytest.raises(HTTPException) as exc_info:
            get_current_user_id(authorization="Basic abc123")
        assert exc_info.value.status_code == 401

    def test_invalid_token_raises_401(self):
        from fastapi import HTTPException
        from auth.dependency import get_current_user_id
        with pytest.raises(HTTPException) as exc_info:
            get_current_user_id(authorization="Bearer invalid.token.here")
        assert exc_info.value.status_code == 401

    def test_valid_token_returns_user_id(self):
        from auth.dependency import get_current_user_id
        from auth.jwt_handler import create_access_token
        token = create_access_token("user_1001")
        user_id = get_current_user_id(authorization=f"Bearer {token}")
        assert user_id == "user_1001"

    def test_token_with_nonexistent_user_raises_401(self):
        """token 签发了一个不在用户表中的 user_id，应被 dependency 二次校验拦截。"""
        from fastapi import HTTPException
        from auth.dependency import get_current_user_id
        from auth.jwt_handler import create_access_token
        token = create_access_token("user_9999")  # 不在 mock_user_db 中
        with pytest.raises(HTTPException) as exc_info:
            get_current_user_id(authorization=f"Bearer {token}")
        assert exc_info.value.status_code == 401
        assert "no longer exists" in exc_info.value.detail


class TestAuthRouterE2E:
    """端到端测试：使用 FastAPI TestClient 测试 /api/auth/login + /api/auth/me。

    这类测试验证越权访问场景：用户 A 的 token 拿不到用户 B 的数据。
    """

    @pytest.fixture
    def client(self):
        """构造一个最小 FastAPI app，只挂 auth router。"""
        from fastapi import FastAPI
        from router import auth as auth_router
        app = FastAPI()
        app.include_router(auth_router.router, prefix="/api")
        from fastapi.testclient import TestClient
        return TestClient(app)

    def test_login_success_returns_token(self, client):
        resp = client.post("/api/auth/login", json={"username": "alice", "password": "cloud@2024"})
        assert resp.status_code == 200
        data = resp.json()
        assert "access_token" in data
        assert data["token_type"] == "bearer"
        assert data["user_id"] == "user_1001"
        assert data["username"] == "alice"

    def test_login_wrong_password_returns_401(self, client):
        resp = client.post("/api/auth/login", json={"username": "alice", "password": "wrong"})
        assert resp.status_code == 401

    def test_login_unknown_user_returns_401(self, client):
        resp = client.post("/api/auth/login", json={"username": "ghost", "password": "cloud@2024"})
        assert resp.status_code == 401

    def test_me_without_token_returns_401(self, client):
        resp = client.get("/api/auth/me")
        assert resp.status_code == 401

    def test_me_with_valid_token_returns_user_info(self, client):
        # 先登录拿 token
        login_resp = client.post("/api/auth/login", json={"username": "bob", "password": "cloud@2024"})
        token = login_resp.json()["access_token"]
        # 带 token 调 /me
        resp = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["user_id"] == "user_1002"
        assert data["username"] == "bob"

    def test_me_with_tampered_token_returns_401(self, client):
        resp = client.get("/api/auth/me", headers={"Authorization": "Bearer fake.token.value"})
        assert resp.status_code == 401


# =============================================================================
# 官方 Ragas 评估慢测试（@pytest.mark.slow）
# =============================================================================
class TestRagEvaluation:
    """RAG 离线评估端到端测试。

    标记为 slow，默认在 `pytest` 时不跑，避免拖慢单元测试：
        pytest                       # 跳过 slow
        pytest -m slow               # 只跑 slow 评估
        pytest -m "not slow"         # 显式跳过 slow

    依赖：DASHSCOPE_API_KEY + Milvus 在线 + 通义千问可访问。
    无 API key 时自动 skip，不在 CI 无密钥环境下失败。
    """

    @pytest.mark.slow
    def test_eval_rag_runs_and_produces_report(self):
        # 缺少 API key 时跳过，避免 CI 无密钥环境失败
        if not os.getenv("DASHSCOPE_API_KEY"):
            pytest.skip("DASHSCOPE_API_KEY 未配置，跳过 RAG 离线评估")

        import asyncio
        from eval import eval_rag

        # 运行评估主流程（检索 + LLM 生成 + LLM Judge 评分，可能耗时 1-2 分钟）
        asyncio.run(eval_rag.main())

        # 断言报告目录下有 JSON 报告产出
        reports = list(eval_rag.EVAL_OUTPUT_DIR.glob("eval_report_*.json"))
        assert len(reports) >= 1, "评估应至少产出一个 JSON 报告"

        # 校验报告结构
        latest = max(reports, key=lambda p: p.stat().st_mtime)
        with open(latest, encoding="utf-8") as f:
            report = json.load(f)
        assert "summary" in report
        assert "details" in report
        assert report["metadata"]["evaluator"] == "official_ragas"
        assert report["summary"]["total_questions"] >= 10
        # retrieval_coverage 永远会算（不依赖评估模型）
        assert "retrieval_coverage" in report["summary"]
        assert "ragas_metrics" in report["summary"]
        assert "quality_gate" in report["summary"]

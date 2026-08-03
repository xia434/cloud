# 云平台多智能体客服系统 (Cloud Agent)

> 面向云平台客服、资源查询与成本优化场景的多智能体应用，基于 LangGraph 编排 RAG、MCP 工具、双层记忆、流式输出、可观测性与安全认证能力。

---

## 亮点速览（TL;DR）

- **多 Agent 编排**：LangGraph Orchestrator 路由 + 5 个业务 Agent + State Handoff 跨 Agent 协同
- **RAG 双引擎**：Milvus 候选召回 + 轻量重排 + Neo4j 知识图谱，单引擎故障自动降级
- **真流式输出**：`graph.astream_events(v2)` 监听 `on_chat_model_stream`，首字延迟从「Agent 推理全时长」降到「LLM 首 token 延迟」
- **双层越权防御**：UserIdInjector 防 LLM Prompt 注入 + JWT 防 HTTP 层伪造
- **可观测 + 可评估**：Langfuse 全链路 trace + 官方 Ragas 四指标与质量门禁
- **工程化实践**：Docker Compose 一键部署、tenacity 重试、aiomysql 异步连接池、CORS 严格配置
- **自动化回归**：默认测试集当前 `64 passed, 1 deselected`，慢速 Ragas 集成测试单独执行

---

## 目录

- [一、项目定位](#一项目定位)
- [二、技术栈全景](#二技术栈全景)
- [三、项目结构](#三项目结构)
- [四、核心架构亮点](#四核心架构亮点)
- [五、效果演示](#五效果演示)
- [六、快速启动](#六快速启动)
- [七、API 端点](#七api-端点)
- [八、工程演进记录](#八工程演进记录)
- [九、模块测试结果](#九模块测试结果)
- [十、当前边界与演进方向](#十当前边界与演进方向)

---

## 一、项目定位

模拟阿里云类云平台的智能客服系统，覆盖五大业务场景：

| 场景 | Agent | 关键能力 |
|------|-------|---------|
| 产品咨询 | ProductAgent | RAG 双引擎（Milvus + Neo4j）+ 自动降级 |
| 账单查询 | BillingAgent | MCP 工具调用 + UserIdInjector 安全拦截 |
| 推广营销 | PromotionAgent | 商品检索 + 千问文生图海报 |
| 选型推荐 | RecommendationAgent | 业务需求分析 + 多源信息融合 |
| FinOps 成本优化 | FinOpsAgent | State Handoff 跨 Agent 协同工作流 |

---

## 二、技术栈全景

| 层级 | 技术 | 亮点 |
|------|------|------|
| Agent 编排 | LangGraph ≥1.1 | Orchestrator 路由 + 条件边 + State Handoff |
| Agent 模式 | create_react_agent | ReAct 思考-行动-观察循环 |
| RAG 检索 | Milvus + 轻量 rerank + Neo4j | 候选 8 → 重排 3 + 图谱精确查询，含降级策略 |
| 工具协议 | MCP (FastMCP) | 9 个工具 + UserIdInjector 安全拦截器 |
| 记忆系统 | Redis 短期 + Milvus 长期 | 后台偏好提取、去重、TTL 管理 |
| 缓存 | Milvus 语义缓存 | L1_EXACT + L1_SEMANTIC 双级 |
| LLM | 通义千问 qwen-plus + text-embedding-v2 + 文生图 | 多模态 |
| 流式输出 | graph.astream_events(v2) | token 级真流式 + Agent 思考过程可视化 |
| 可观测性 | Langfuse | LLM/工具调用/Token 消耗全链路追踪 |
| 评估 | Ragas 0.4.x | 真实 ProductAgent 样本 + 四指标 + 可配置质量门禁 |
| 安全认证 | JWT (PyJWT) + bcrypt (passlib) | 严格模式 + 越权防护 + CORS 收紧 |
| Web | FastAPI + SSE | lifespan 异步初始化 + Depends 注入 user_id |
| 前端 | Vue3 + TS + Element Plus | SSE 流式接收 + 思考链可视化 + 登录态管理 |
| 部署 | Docker Compose | 一键拉起全部依赖 |

---

## 三、项目结构

```
cloud_agent/
├── agent/                          # Agent 核心代码
│   ├── agents/                     # 5 个业务 Agent + Orchestrator
│   ├── core/
│   │   ├── workflow/               # LangGraph 图编排 + State
│   │   ├── memory/                 # 双层记忆系统
│   │   ├── graph/                  # Neo4j 知识图谱
│   │   └── llm_factory.py          # 带重试的 LLM 工厂 (P2-10)
│   ├── tools/                      # vector_tool + graph_tool
│   ├── mcp_servers/                # MCP 工具服务 (FastMCP)
│   ├── prompts/                    # Prompt 模板集中管理 (P1-8)
│   ├── eval/                       # 官方 Ragas 离线 RAG 评估
│   ├── tests/                      # pytest 单元测试 (P2-9, P3-15)
│   └── config/                     # settings + mcp_servers.json
├── app/                            # FastAPI Web 层
│   ├── auth/                       # P3 安全认证体系
│   │   ├── jwt_handler.py          # JWT 签发/验证 (PyJWT)
│   │   ├── models.py               # mock 用户表 + bcrypt
│   │   └── dependency.py           # FastAPI Depends 注入 user_id
│   ├── router/                     # chat / health / history / auth 路由
│   ├── service/chat_service.py     # 真流式 + Langfuse 注入 (P0-1, P0-2)
│   └── infra/
│       ├── cache.py                # Milvus 语义缓存
│       └── observability.py        # Langfuse 集成 + 降级 (P0-2)
├── front/cloud_agent/              # Vue3 前端
│   └── src/App.vue                 # SSE 接收 + 思考链可视化 + 历史持久化 + 登录态 (P3-16)
├── mock_data/                      # 6 份知识文档
├── docker-compose.yml              # 一键部署 (P1-6)
└── README.md
```

---

## 四、核心架构亮点

### 4.1 多 Agent 编排与 State Handoff

[graph_manager.py](agent/core/workflow/graph_manager.py) 用 LangGraph 构建 Orchestrator 路由 + 5 个业务节点的有向图：
- Orchestrator 用 LLM 做意图分类（非关键词匹配）
- **State Handoff**：BillingAgent → FinOpsAgent 通过 `metadata.is_finops_workflow` 共享状态实现跨 Agent 协同
- 默认兜底到 product_agent，保证系统总会有响应

### 4.2 RAG 双引擎 + 自动降级

[graph_tool.py](agent/tools/graph_tool.py) + [vector_tool.py](agent/tools/vector_tool.py)：
- GraphCypherQAChain 失败时自动降级为关键词检索
- 体现了**生产级鲁棒性思维**

### 4.3 MCP 协议 + 安全拦截器

[billing_agent.py](agent/agents/billing_agent.py) 的 `UserIdInjector` 拦截 LLM 调用，强制从 runtime config 注入真实 user_id，防止 Prompt 注入越权查询他人数据。

### 4.4 双层记忆 + 后台提取

[memory_manager.py](agent/core/memory/memory_manager.py)：
- 每 5 轮后台触发偏好提取
- 会话结束强制提取并清理 Redis
- 去重机制避免重复存储

### 4.5 L1 语义缓存

[cache.py](app/infra/cache.py)：
- 双级匹配：精确归一化 → 余弦距离 < 0.08 语义匹配
- scope 策略：用户专属缓存优先于公共缓存

### 4.6 JWT 安全认证体系（P3 新增）

[jwt_handler.py](app/auth/jwt_handler.py) + [dependency.py](app/auth/dependency.py)：
- **HTTP 层防伪造**：user_id 强制从 `Authorization: Bearer <token>` 解析，不再信任 body/query
- **双层防御**：UserIdInjector 防 LLM Prompt 注入 + JWT 防 HTTP 层伪造，组合构成完整越权防护
- **严格模式**：未携 token / token 过期 / token 篡改 / 用户已删除 一律 401
- **CORS 收紧**：显式来源列表，禁止 `'*'` + `allow_credentials=True` 反模式
- **二次校验**：dependency 层校验 user_id 仍存在于用户表，防止已删除用户的 token 继续生效

---

## 五、可复现验证

### 5.1 自动化回归

```bash
cd agent
pytest -q
# 当前基线：64 passed, 1 deselected
```

默认回归不访问外部模型；真实 LangGraph + Ragas 评估标记为慢速任务，避免日常测试产生 API 费用。

### 5.2 服务验收

启动依赖和应用后，可验证健康检查、JWT 登录与 SSE 对话：

```bash
curl http://localhost:5000/api/health
curl -X POST http://localhost:5000/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"alice","password":"cloud@2024"}'
```

Langfuse 配置成功后，每次请求会记录 Orchestrator 路由、LLM 调用、工具耗时与 Token 用量；未配置或服务不可用时主对话链路自动降级。

### 5.3 RAG 离线评估报告

轻量重排与图谱证据补查上线前的真实 LangGraph 全链路基线（2026-07-31，11 条黄金样本）：

| 指标 | 实测 | 门槛 | 状态 |
|------|------|------|------|
| Agent 路由准确率 | 1.000 | 1.000 | 通过 |
| Faithfulness | 0.790 | 0.750 | 通过 |
| Answer relevancy | 0.459 | 0.700 | 未通过 |
| Context precision | 0.439 | 0.650 | 未通过 |
| Context recall | 0.448 | 0.600 | 未通过 |
| 文档来源覆盖率 | 0.591 | 观察项 | - |

质量门禁当前**未通过**。这份基线没有通过降低阈值或使用预制答案美化：评估脚本会执行编译后的 LangGraph，采集真实路由、工具上下文和最终回答，再交给官方 Ragas 0.4.x。完整报告见 [agent/eval/results/eval_report_latest.json](agent/eval/results/eval_report_latest.json)。

基于该基线已完成第一轮快速优化：Milvus 先召回 8 条候选，本地轻量重排后只保留 3 条；ProductAgent 仅命中图谱时自动补查向量证据；最终合成必须逐项覆盖用户子问题。11 条黄金问题的低成本检索冒烟已达到文档来源 `11/11` 完整覆盖，但尚未重跑依赖 LLM Judge 的 Ragas 四指标，因此不能据此声明质量门禁已通过。

---

## 六、快速启动

### 6.1 启动依赖服务

```bash
# 一键拉起全部依赖（Redis/MySQL/Neo4j/Milvus/Langfuse）
docker compose up -d

# 查看状态
docker compose ps
```

### 6.2 配置环境变量

复制 [agent/.env.example](agent/.env.example) 为 `agent/.env`，再填写本地配置：

```bash
DASHSCOPE_API_KEY=你的通义千问API Key
REDIS_URL=redis://:redis123456@localhost:6379
MILVUS_HOST=localhost
MILVUS_PORT=19530
NEO4J_URI=bolt://localhost:7687
NEO4J_PASSWORD=neo4j123456
MYSQL_HOST=localhost
MYSQL_USER=root
MYSQL_PASSWORD=root123456
MYSQL_DATABASE=cloud_platform

# Langfuse（可选，不配置则自动降级）
LANGFUSE_PUBLIC_KEY=你的Langfuse公钥
LANGFUSE_SECRET_KEY=你的Langfuse密钥
LANGFUSE_HOST=http://localhost:3000

# JWT 认证（P3 必填，严格模式）
# 生产环境用 openssl rand -hex 32 生成
JWT_SECRET=cloud_agent_dev_secret_change_me_in_production_a1b2c3d4e5
JWT_ALGORITHM=HS256
JWT_EXPIRE_HOURS=24

# CORS 来源（逗号分隔，禁止 '*'）
CORS_ORIGINS=http://localhost:5175,http://localhost:5173,http://localhost:8080
```

### 6.3 测试账号

P3 安全认证体系启用后，前端打开会弹登录窗。3 个 mock 账号：

| 用户名 | 密码 | user_id | 角色 | 显示名 |
|--------|------|---------|------|--------|
| alice | `cloud@2024` | user_1001 | user | Alice (产品经理) |
| bob | `cloud@2024` | user_1002 | user | Bob (运维工程师) |
| admin | `cloud@2024` | user_1003 | admin | Admin (管理员) |

> 生产环境请将 mock 用户表替换为数据库 + bcrypt，并修改默认密码。

### 6.4 安装依赖并启动后端

```bash
cd agent
pip install -r requirements.txt

cd ../app
python app_main.py
# 后端启动在 http://localhost:5000
```

### 6.5 启动前端

```bash
cd front/cloud_agent
npm install
npm run dev
# 前端启动在 http://localhost:5175
```

### 6.6 运行 RAG 评估（可选）

```bash
cd agent
python -m eval.eval_rag
# 评估报告输出到 agent/eval/results/

# CI/质量门禁模式：任一指标不达标时退出码为 2
python -m eval.eval_rag --enforce-thresholds
```

### 6.7 运行单元测试（可选）

```bash
cd agent
pip install pytest pytest-asyncio httpx
pytest tests/ -v
```

### 6.8 健康检查

```bash
curl http://localhost:5000/api/health
# 返回 graph/memory/cache/observability 状态
```

---

## 七、API 端点

| 方法 | 路径 | 鉴权 | 说明 |
|------|------|------|------|
| POST | /api/auth/login | 否 | 用户名+密码登录，签发 JWT |
| GET | /api/auth/me | 是 | 拉取当前登录用户信息（校验 token） |
| POST | /api/chat | 是 | SSE 流式聊天（真流式 + 思考过程元数据） |
| GET | /api/history?session_id=xxx | 是 | 拉取会话历史（user_id 由 JWT 解析） |
| GET | /api/health | 否 | 系统健康检查（图/记忆/缓存/可观测性状态） |

> 鉴权接口需在请求头携带 `Authorization: Bearer <token>`，token 通过 `/api/auth/login` 获取。

### SSE 事件协议

```
data: {"content": "VPC"}                    # 内容流（token 级）
data: {"type": "route", "agent": "..."}     # 路由完成事件
data: {"type": "tool_start", "name": "..."} # 工具调用开始
data: {"type": "tool_end", "name": "..."}   # 工具调用结束
data: {"type": "cache_hit", "level": "..."} # 缓存命中
data: {"done": true}                        # 流结束
```

---

## 八、工程演进记录

### P0 - 必补强项（已完成）

| 编号 | 主题 | 问题 | 改造 |
|------|------|------|------|
| P0-1 | 真流式改造 | 原 `ainvoke()` 同步等待再切片 yield，首字延迟 = 整个推理时间 | [chat_service.py](app/service/chat_service.py) 改用 `astream_events(v2)` 监听 `on_chat_model_stream`，输出 token 级真流式 + `route`/`tool_start`/`tool_end`/`cache_hit` 元数据事件；修复缓存写入 bug；前端 [App.vue](front/cloud_agent/src/App.vue) 新增思考过程可视化 |
| P0-2 | Langfuse 可观测性 | Agent 系统无 trace 等于裸奔 | 新增 [observability.py](app/infra/observability.py)（含优雅降级）；注入 Langfuse callback 到 graph config；新增 [/api/health](app/router/health.py) 诊断端点 |
| P0-3 | Ragas RAG 离线评估 | 缺少 RAG 评估体系 | 新增 [agent/eval/](agent/eval/dataset.py)：11 条黄金 QA + 官方四指标 + 本地检索覆盖率 + 可配置阈值与非零退出码 |

### P1 - 强烈建议补强（已完成）

| 编号 | 主题 | 问题 | 改造 |
|------|------|------|------|
| P1-4 | MCP 异步化 | 同步 PyMySQL 在 FastMCP 异步上下文阻塞事件循环 | [cloud_platform_server.py](agent/mcp_servers/cloud_platform_server.py) 改用 `aiomysql.create_pool` 全局连接池；未安装时降级同步模式 |
| P1-5 | 修复工具重复定义 | 两个同名 `get_promotion_materials` 后者覆盖前者，精确 product_id 拿到兜底数据 | 合并为单一实现：优先精确 product_id 匹配，否则关键词模糊匹配，统一输出 `poster_url` |
| P1-6 | docker-compose | 缺少一键部署 | 新增 [docker-compose.yml](docker-compose.yml)，覆盖 Redis/MySQL/Neo4j/Milvus(含 etcd+MinIO)/Langfuse，全部带 healthcheck |
| P1-7 | 前端历史持久化 | switchSession 清空 messages 丢失历史 | 新增 [/api/history](app/router/history.py) 从 Redis 拉取；前端切换会话调接口并降级为空会话 |
| P1-8 | Prompt 治理 | system_prompt 散落各 agent 无版本管理 | 新增 [templates.py](agent/prompts/templates.py) 集中管理 7 个常量 + `format_memory_context`；6 个 agent 改为引用常量 |

### P2 - 锦上添花（已完成）

| 编号 | 主题 | 问题 | 改造 |
|------|------|------|------|
| P2-9 | pytest 单元测试 | - | 新增 [test_unit.py](agent/tests/test_unit.py)，覆盖 Prompt/可观测性降级/MCP/安全/流式策略/评估与检索重排 |
| P2-10 | LLM 重试机制 | 直接 `ChatOpenAI()` 无重试，网络抖动即崩溃 | 新增 [llm_factory.py](agent/core/llm_factory.py)（tenacity 指数退避 + 可重试异常过滤，包装 invoke/ainvoke/stream/astream/astream_events）；6 个 agent 全部改用工厂 |

### P3 - 生产级安全认证体系（已完成）

| 编号 | 主题 | 问题 | 改造 |
|------|------|------|------|
| P3-11 | JWT 后端基础设施 | HTTP 层 user_id 可伪造越权，UserIdInjector 防不了 HTTP 伪造 | 新增 [app/auth/](app/auth/__init__.py)：[jwt_handler.py](app/auth/jwt_handler.py)（HS256）+ [models.py](app/auth/models.py)（3 个 mock 用户 bcrypt）+ [dependency.py](app/auth/dependency.py)（Depends 解析 + 二次校验存在性）；严格模式一律 401 |
| P3-12 | 接入 auth 路由 | - | 新增 [auth.py](app/router/auth.py)（login + me）；chat/history 改用 `Depends(get_current_user_id)`；[schemas/chat.py](app/schemas/chat.py) 移除 user_id；登录失败统一 401 防枚举 |
| P3-13 | CORS 收紧 | `allow_origins=["*"]` + credentials 是规范反模式 | 来源从 .env 读取 + validator 拒绝 `'*'`；显式枚举 methods/headers 含 `Authorization`；加载失败降级本地端口 |
| P3-14 | 配置层补全 | - | [settings.py](agent/config/settings.py) 加 `jwt_secret`(≥16 字符)/`jwt_algorithm`/`jwt_expire_hours`/`cors_origins` 字段及 validator；[.env.example](agent/.env.example) 补充默认项 |
| P3-15 | JWT/越权单元测试 | - | [test_unit.py](agent/tests/test_unit.py) 新增 TestJWTHandler/TestMockUserDB/TestAuthDependency/TestAuthRouterE2E 四组测试 |
| P3-16 | 前端接入 JWT | [App.vue](front/cloud_agent/src/App.vue) 硬编码 `user_1001` 同一身份 | 新增登录弹窗 + localStorage 持久化；请求自动加 Bearer header；401 自动清空弹窗；onMounted 校验 token；新增退出按钮 |

---

## 九、模块测试结果

### 静态语法测试

通过 `python -m py_compile` 对 21 个改造文件做语法验证，**全部通过**：

| 模块 | 文件 | 状态 |
|------|------|------|
| 真流式 | app/service/chat_service.py | ✅ |
| 可观测性 | app/infra/observability.py | ✅ |
| 新增路由 | app/router/health.py、history.py、auth.py | ✅ |
| Web 入口 | app/app_main.py | ✅ |
| MCP 异步化 | agent/mcp_servers/cloud_platform_server.py | ✅ |
| Prompt 治理 | agent/prompts/templates.py | ✅ |
| LLM 重试 | agent/core/llm_factory.py | ✅ |
| RAG 评估 | agent/eval/eval_rag.py | ✅ |
| 单元测试 | agent/tests/test_unit.py | ✅ |
| 6 个 Agent | agent/agents/*.py | ✅ |
| **P3 JWT 后端** | app/auth/jwt_handler.py、models.py、dependency.py、__init__.py | ✅ |
| **P3 auth 路由** | app/router/auth.py | ✅ |
| **P3 配置层** | agent/config/settings.py | ✅ |
| **P3 chat/history 接入** | app/router/chat.py、history.py、schemas/chat.py | ✅ |

### 缺陷修复记录

静态测试过程中发现并修复了以下缺陷：

| 优先级 | 缺陷 | 修复方案 |
|--------|------|---------|
| 🔴 P0 | `cloud_platform_server.py` 中 `aiomysql.DictCursor` 作用域未定义，运行时 NameError | 在 `_fetch_all` 函数内部 `import aiomysql` |
| 🔴 P0 | 5 个 agent 漏改 `create_llm_with_retry`，仍直接 `ChatOpenAI()` | 全部改用 LLM 工厂 |
| 🟡 P1 | ORCHESTRATOR_PROMPT 提到不存在的 deep_research_agent | 改为路由到 product_agent 并提示功能未上线 |
| 🟡 P1 | test_unit.py 导入 `_sse` 触发 Settings 实例化 | 改用 inline 复刻等价实现 |
| 🟡 P1 | TestPromotionMaterialsTool 直接调用 FastMCP 装饰后的工具 | 改用 `.fn` 属性获取底层函数 |

---

## 十、当前边界与演进方向

项目当前定位是可复现的工程化原型，以下边界已明确记录，便于后续接入真实业务环境：

| 领域 | 当前实现 | 演进方向 |
|------|----------|----------|
| 身份与权限 | JWT + UserIdInjector 已完成请求级身份隔离；用户表为开发环境内存数据，角色字段已保留 | 接入持久化用户中心、密码策略和完整 RBAC |
| RAG 评估 | 11 条黄金样本、官方 Ragas 四指标、可配置质量门禁；轻量 rerank 已接入 | 用优化后的检索链路重新跑 Ragas，并扩展困难样本集 |
| 图谱可追溯性 | 图谱结果可参与回答，ProductAgent 会补查向量文档来源 | 为图节点和关系补充 `source`、版本和更新时间 |
| 规模验证 | 已使用异步连接池、超时和重试机制；尚未完成生产流量级压测 | 增加并发压测、P95 延迟、吞吐量和失败率指标 |

上述边界不影响本地启动、核心 Agent 编排和自动化回归；它们是从工程原型走向生产系统时的明确扩展点。

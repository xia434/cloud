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
- [十、已知遗留问题](#十已知遗留问题)

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

### P0 - 必补强项（评估基础设施已完成，质量门禁持续优化）

#### P0-1 真流式改造

**问题**：原实现用 `graph.ainvoke()` 同步等待完整结果，再切片 yield（伪流式），首字延迟 = 整个 Agent 推理时间。

**改造**：[chat_service.py](app/service/chat_service.py) 改用 `graph.astream_events(version="v2")` 监听 `on_chat_model_stream` 事件，实现 token 级真流式；同时输出 `route`/`tool_start`/`tool_end`/`cache_hit` 元数据事件；修复原实现未调用 `set_cache` 写入缓存的 bug。前端 [App.vue](front/cloud_agent/src/App.vue) 新增 Agent 执行过程可视化。

#### P0-2 集成 Langfuse 可观测性

**问题**：Agent 系统在生产环境没有 trace 等于裸奔。

**改造**：新增 [app/infra/observability.py](app/infra/observability.py)（含优雅降级）；chat_service.py 注入 Langfuse callback 到 graph config；新增 [/api/health](app/router/health.py) 诊断端点；.env + settings.py 加入 Langfuse 配置项。

#### P0-3 官方 Ragas RAG 离线评估

**问题**：缺少 RAG 评估体系，无法评估 RAG 质量。

**改造**：新增 [agent/eval/](agent/eval/dataset.py) 模块：
- 11 条覆盖 6 份文档和 Product/Recommendation 路由的黄金标准 QA pairs
- 官方 Ragas 四大指标（faithfulness/answer_relevancy/context_precision/context_recall）
- 本地检索覆盖率（不依赖评估模型）
- 可配置阈值与非零退出码，输出逐样本 JSON 报告供回归核查

### P1 - 强烈建议补强（已完成）

#### P1-4 修复 MCP server 同步阻塞

**问题**：[cloud_platform_server.py](agent/mcp_servers/cloud_platform_server.py) 用同步 PyMySQL，在 FastMCP 异步上下文里会阻塞事件循环。

**改造**：用 `aiomysql.create_pool` 创建全局连接池（懒加载）；3 个 DB 工具改为 async；未安装 aiomysql 时降级到 PyMySQL 同步模式。

#### P1-5 修复 get_promotion_materials 重复定义 bug

**问题**：原文件存在两个同名函数（按 product_id 和按 product_name），后者覆盖前者，导致 PromotionAgent 按精确 product_id 调用时拿到 default 兜底数据。

**改造**：合并为单一实现，优先精确 product_id 匹配，匹配不到走关键词模糊匹配，统一输出 `poster_url` 字段。

#### P1-6 编写 docker-compose.yml

**改造**：新增 [docker-compose.yml](docker-compose.yml)，覆盖 Redis/MySQL/Neo4j/Milvus(含 etcd+MinIO)/Langfuse，全部带 healthcheck，一键 `docker compose up -d` 拉起。

#### P1-7 前端对话历史持久化

**问题**：[App.vue](front/cloud_agent/src/App.vue) 的 `switchSession` 直接清空 `messages`，会话切换丢失历史。

**改造**：新增 [/api/history](app/router/history.py) 路由从 Redis 拉取会话历史；前端 switchSession 改为调接口拉取历史并降级为空会话。

#### P1-8 Prompt 抽离到 prompts 目录

**问题**：所有 system_prompt 散落在各 agent 的 `__call__` 里，没有版本管理。

**改造**：新增 [agent/prompts/templates.py](agent/prompts/templates.py)（7 个 Prompt 常量 + `format_memory_context` 工具函数）；6 个 agent 改为引用常量。

### P2 - 锦上添花（已完成）

#### P2-9 补充 pytest 单元测试

**改造**：新增 [agent/tests/test_unit.py](agent/tests/test_unit.py)，覆盖 Prompt、可观测性降级、MCP、安全、流式策略、评估与检索重排等逻辑。

#### P2-10 LLM 调用加重试机制

**问题**：所有 Agent 直接 `ChatOpenAI(...)` 创建 LLM，没有重试机制，网络抖动即全流程崩溃。

**改造**：新增 [agent/core/llm_factory.py](agent/core/llm_factory.py)（tenacity 重试 + 指数退避 + 可重试异常过滤，包装 invoke/ainvoke/stream/astream/astream_events 五个方法）；6 个 agent 全部改用工厂。

### P3 - 生产级安全认证体系（已完成）

#### P3-11 后端 JWT 认证基础设施

**问题**：`/api/chat` 与 `/api/history` 直接信任 body/query 里的 `user_id`，HTTP 层任意伪造可越权查询他人账单/历史。UserIdInjector 只能防 LLM Prompt 注入，防不了 HTTP 层伪造。

**改造**：
- 新增 [app/auth/](app/auth/__init__.py) 模块：
  - [jwt_handler.py](app/auth/jwt_handler.py)：HS256 签发/验证，过期与无效分别抛 `TokenExpiredError` / `InvalidTokenError`
  - [models.py](app/auth/models.py)：3 个 mock 用户（alice/bob/admin，密码 `cloud@2024`），bcrypt hash
  - [dependency.py](app/auth/dependency.py)：FastAPI Depends 从 Authorization header 解析 user_id，并对 user_id 二次校验存在性
- 严格模式：未携 token / 过期 / 篡改 / 用户已删除 一律 401，并返回 `WWW-Authenticate: Bearer` 响应头

#### P3-12 接入 auth 路由 + 修改现有路由

**改造**：
- 新增 [app/router/auth.py](app/router/auth.py)：`POST /api/auth/login`（用户名+密码 → JWT）+ `GET /api/auth/me`（带 token 拉用户信息）
- [chat.py](app/router/chat.py) 与 [history.py](app/router/history.py) 改用 `Depends(get_current_user_id)`，user_id 强制来自 JWT
- [schemas/chat.py](app/schemas/chat.py) 移除 `user_id` 字段，即便 body 塞了也会被 Pydantic 忽略
- 登录失败统一返回 401（不区分用户名错误/密码错误，防止用户名枚举）

#### P3-13 CORS 收紧 + 配置化

**问题**：[app_main.py](app/app_main.py) 原 CORS 配置 `allow_origins=["*"]` + `allow_credentials=True` 是 CORS 规范的反模式，浏览器会忽略 credentials。

**改造**：
- CORS 来源从 .env 读取（`CORS_ORIGINS`，逗号分隔），settings.py 加 validator 拒绝 `'*'`
- `allow_methods` / `allow_headers` 显式枚举，包含 `Authorization` header
- settings 加载失败时降级到只允许本地开发端口

#### P3-14 settings.py 与 .env 增加 JWT/CORS 配置项

**改造**：[settings.py](agent/config/settings.py) 加 4 个字段 + 2 个 validator：
- `jwt_secret`（必填，≥16 字符）、`jwt_algorithm`（默认 HS256）、`jwt_expire_hours`（默认 24）
- `cors_origins`（必填，拒绝 `'*'`）
- [.env.example](agent/.env.example) 补充默认配置项

#### P3-15 补充 JWT/越权访问单元测试

**改造**：[test_unit.py](agent/tests/test_unit.py) 新增 JWT 与越权访问测试：
- `TestJWTHandler`：签发/解码/篡改检测/claim 完整性
- `TestMockUserDB`：登录成功/密码错误/未知用户/按 ID 查询
- `TestAuthDependency`：缺 header/格式错误/无效 token/有效 token/用户已删除
- `TestAuthRouterE2E`：用 FastAPI TestClient 端到端测试 login + me + 401 场景

#### P3-16 前端接入 JWT

**问题**：[App.vue](front/cloud_agent/src/App.vue) 3 处硬编码 `user_1001`，任何人打开页面都是同一个身份。

**改造**：
- 新增登录弹窗（用户名+密码），调用 `/api/auth/login` 拿 token
- token 与 currentUser 持久化到 localStorage（`cloud_agent_token` / `cloud_agent_user`）
- 所有 `/api/chat` / `/api/history` 请求自动加 `Authorization: Bearer <token>` header
- 移除 3 处硬编码 `user_1001`，用户名/头像首字母从 `currentUser` 动态渲染
- 401 自动清空 token + 弹登录窗 + ElMessage 提示
- onMounted 校验 token 有效性（调 `/api/auth/me`），失效自动弹登录
- 新增「退出」按钮，清空 localStorage 与消息列表

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

## 十、已知遗留问题

| 优先级 | 模块 | 问题 | 影响 |
|--------|------|------|------|
| 🟢 低 | product_agent.py / billing_agent.py 的 `__main__` 块 | `get_*_agent()` 函数返回 None，手动调试会崩 | 仅影响手动运行，不影响图编排 |
| 🟢 低 | cloud_platform_server.py | `import time`、`import asyncio` 未使用 | 死导入，无功能影响 |
| 🟢 低 | App.vue | `[DONE]` 判断是死代码 | 后端不发该标记，无功能影响 |
| 🟢 低 | auth/models.py | mock 用户表为内存 dict，未持久化 | 演示用，生产应替换为数据库 |
| 🟡 中 | RBAC | 当前所有登录用户权限等价，未实现 admin/user 角色差异化接口 | FinOps 等敏感操作未做角色校验 |
| 🔴 高 | RAG 检索质量 | 优化前 Ragas 基线中 context precision=0.439、recall=0.448，均未过门禁 | 轻量 rerank 已接入，仍需重新评估并按结果迭代 |
| 🟡 中 | 图谱原生来源追溯 | Neo4j 工具本身仍只返回 `knowledge_graph` | ProductAgent 已补查向量文档缓解；后续应在图数据中写入 source 属性 |
| 🟡 中 | 评估集规模 | 当前只有 11 条黄金样本 | 可做回归基线，但不足以代表生产流量分布 |

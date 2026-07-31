"""Application settings using Pydantic Settings."""

import os
from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""
    
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )
    
    # LLM Configuration
    dashscope_api_key: str = Field(alias="DASHSCOPE_API_KEY")
    model: str = Field(default="qwen-plus", alias="MODEL")
    base_url: str | None = Field(default=None, alias="BASE_URL")
    
    # MCP Configuration
    mcp_servers_config: Path = Field(
        default=Path(__file__).parent / "mcp_servers.json",
        alias="MCP_SERVERS_CONFIG"
    )
    
    # Weather API
    openweather_api_key: str | None = Field(default=None, alias="OPENWEATHER_API_KEY")
    
    # Redis (short-term memory)
    redis_url: str = Field(default="redis://localhost:6379", alias="REDIS_URL")
    redis_ttl: int = Field(default=1800, alias="REDIS_TTL")  # seconds
    
    # Milvus (long-term memory)
    milvus_host: str = Field(default="localhost", alias="MILVUS_HOST")
    milvus_port: int = Field(default=19530, alias="MILVUS_PORT")
    milvus_api_key: str | None = Field(default=None, alias="MILVUS_API_KEY")
    
    # Neo4j (knowledge graph)
    neo4j_uri: str = Field(default="bolt://localhost:7687", alias="NEO4J_URI")
    neo4j_user: str = Field(default="neo4j", alias="NEO4J_USER")
    neo4j_password: str = Field(default="password", alias="NEO4J_PASSWORD")
    neo4j_database: str = Field(default="neo4j", alias="NEO4J_DATABASE")

    # Logging
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")

    # Langfuse (可观测性，可选 - 未配置则自动降级)
    langfuse_public_key: str | None = Field(default=None, alias="LANGFUSE_PUBLIC_KEY")
    langfuse_secret_key: str | None = Field(default=None, alias="LANGFUSE_SECRET_KEY")
    langfuse_host: str = Field(default="http://localhost:3000", alias="LANGFUSE_HOST")

    # JWT 认证配置 (P3 安全认证体系)
    jwt_secret: str = Field(alias="JWT_SECRET")
    jwt_algorithm: str = Field(default="HS256", alias="JWT_ALGORITHM")
    jwt_expire_hours: int = Field(default=24, alias="JWT_EXPIRE_HOURS")

    # CORS 配置 (P3 安全认证体系 - 收紧 allow_origins)
    # 逗号分隔的来源列表，例如 "http://localhost:5175,http://localhost:5173"
    cors_origins: str = Field(
        default="http://localhost:5175,http://localhost:5173,http://localhost:8080",
        alias="CORS_ORIGINS",
    )

    @field_validator("dashscope_api_key")
    @classmethod
    def validate_api_key(cls, v: str) -> str:
        """Validate API key is not empty."""
        if not v or v.strip() == "":
            raise ValueError("DASHSCOPE_API_KEY cannot be empty")
        return v.strip()

    @field_validator("jwt_secret")
    @classmethod
    def validate_jwt_secret(cls, v: str) -> str:
        """JWT 密钥长度校验：至少 16 字符，避免弱密钥导致签名被暴力破解。"""
        if not v or len(v.strip()) < 16:
            raise ValueError(
                "JWT_SECRET must be at least 16 characters to prevent brute-force attacks"
            )
        return v.strip()

    @field_validator("cors_origins")
    @classmethod
    def validate_cors_origins(cls, v: str) -> str:
        """CORS 来源校验：拒绝通配符 '*'，避免与 allow_credentials=True 组合的反模式。"""
        if not v or v.strip() == "":
            raise ValueError("CORS_ORIGINS cannot be empty (do not use '*' in production)")
        origins = [o.strip() for o in v.split(",") if o.strip()]
        if "*" in origins:
            raise ValueError(
                "CORS_ORIGINS must not contain '*' when allow_credentials=True (CORS spec violation)"
            )
        return ",".join(origins)
    
    def get_model_config(self) -> dict[str, Any]:
        """Get model configuration for LangChain."""
        config: dict[str, Any] = {
            "model": self.model,
            "api_key": self.dashscope_api_key,
        }
        if self.base_url:
            config["base_url"] = self.base_url
        return config


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()


def load_mcp_servers_config(config_path: Path | None = None) -> dict[str, Any]:
    """加载 mcp_servers.json，并展开 ${ENV_VAR} 占位符。

    解决原配置中硬编码 `D:\\python312\\python.exe` 在其他机器 / Docker
    环境下无法运行的问题。

    支持的占位符：
    - ${PYTHON_EXEC}: MCP Server 子进程的 Python 解释器路径。
      默认取当前进程的 sys.executable，确保 MCP 子进程与 Agent 主进程
      使用同一解释器（依赖一致，避免被 PATH 中其他 python 抢先匹配）。
      可通过环境变量 PYTHON_EXEC 显式覆盖。
    - 其他 ${VAR}: 按 os.path.expandvars 规则展开。
    """
    import json
    import sys

    path = config_path or get_settings().mcp_servers_config
    with open(path, "r", encoding="utf-8") as f:
        config = json.load(f)

    # PYTHON_EXEC 默认用当前解释器（最稳妥：子进程继承主进程的依赖环境）
    os.environ.setdefault("PYTHON_EXEC", sys.executable)

    # MCP 配置文件位于 agent/config/ 目录，cwd 相对路径应以 agent/ 为基准
    # 注意：agent_root 已是 agent/ 目录本身，因此 cwd 是相对 agent/ 的子路径
    # （如 "." → agent/，"config" → agent/config/），不要再写 "agent"
    agent_root = os.path.dirname(os.path.dirname(os.path.abspath(path)))

    for name, server in config.get("mcpServers", {}).items():
        cmd = server.get("command", "")
        if "${" in cmd:
            server["command"] = os.path.expandvars(cmd)
        # cwd 相对路径转绝对路径，避免子进程因工作目录不存在而启动失败（WinError 267）
        cwd = server.get("cwd", "")
        if cwd and not os.path.isabs(cwd):
            server["cwd"] = os.path.join(agent_root, cwd)

        # 启动时校验：cwd 必须存在且是目录，否则 MCP 子进程会报 WinError 267
        # 在此抛出明确错误，便于定位配置问题（而非等到子进程启动时才失败）
        if cwd:
            resolved_cwd = server["cwd"]
            if not os.path.isdir(resolved_cwd):
                raise ValueError(
                    f"MCP server '{name}' 配置错误：cwd 目录不存在: "
                    f"{resolved_cwd}\n"
                    f"提示：cwd 相对路径以 agent/ 目录为基准，"
                    f"请使用 '.' 而非 'agent'。"
                )

    return config


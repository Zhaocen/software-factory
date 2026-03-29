from __future__ import annotations

import yaml
from pathlib import Path
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # API Keys
    anthropic_api_key: str = Field(default="", alias="ANTHROPIC_API_KEY")
    openai_api_key: str = Field(default="", alias="OPENAI_API_KEY")
    # OpenAI 兼容服务的全局 API Key（也可在 config.yaml 的 agent 配置中单独指定）
    openai_compatible_api_key: str = Field(default="", alias="OPENAI_COMPATIBLE_API_KEY")

    # 服务配置
    host: str = Field(default="0.0.0.0", alias="HOST")
    port: int = Field(default=8000, alias="PORT")
    debug: bool = Field(default=False, alias="DEBUG")

    # MySQL 数据库配置
    # 可以直接设置完整 URL，也可以分项配置
    db_url: str = Field(default="", alias="DB_URL")
    db_host: str = Field(default="localhost", alias="DB_HOST")
    db_port: int = Field(default=3306, alias="DB_PORT")
    db_user: str = Field(default="root", alias="DB_USER")
    db_password: str = Field(default="", alias="DB_PASSWORD")
    db_name: str = Field(default="software_factory", alias="DB_NAME")

    @property
    def database_url(self) -> str:
        """返回 asyncmy/aiomysql 格式的数据库 URL"""
        if self.db_url:
            return self.db_url
        return (
            f"mysql+aiomysql://{self.db_user}:{self.db_password}"
            f"@{self.db_host}:{self.db_port}/{self.db_name}"
            "?charset=utf8mb4"
        )

    # 配置文件路径
    config_yaml_path: str = Field(default="config.yaml", alias="CONFIG_YAML_PATH")

    # 运行时加载的配置（不从环境变量读取）
    _agents_config: dict = {}
    _docker_config: dict = {}
    _retry_config: dict = {}
    _output_config: dict = {}
    _llm_providers: list = []

    def model_post_init(self, __context: object) -> None:
        config_path = Path(self.config_yaml_path)
        if config_path.exists():
            with open(config_path) as f:
                full_config = yaml.safe_load(f) or {}
            self._agents_config = full_config.get("agents", {})
            self._docker_config = full_config.get("docker", {})
            self._retry_config = full_config.get("retry", {})
            self._output_config = full_config.get("output", {})
            self._llm_providers = full_config.get("llm_providers", [])

    def get_agent_model_config(self, agent_name: str) -> dict:
        return self._agents_config.get(agent_name, {})

    def get_llm_provider(self, provider_id: str) -> dict:
        """按 ID 查找 llm_providers 中的供应商配置"""
        for p in self._llm_providers:
            if p.get("id") == provider_id:
                return p
        return {}

    def get_docker_config(self) -> dict:
        return self._docker_config

    def get_retry_config(self) -> dict:
        return self._retry_config

    def get_output_config(self) -> dict:
        return self._output_config

    @property
    def max_retries(self) -> int:
        return self._retry_config.get("max_retries", 3)

    @property
    def output_base_dir(self) -> str:
        return self._output_config.get("base_dir", "projects")


# 全局单例
_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings

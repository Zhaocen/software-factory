"""配置服务：从数据库读写系统配置，并在首次启动时从 config.yaml 导入种子数据。"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from software_factory.db.models import SystemConfig

logger = logging.getLogger(__name__)

# 所有配置 key
KEYS = ("llm_providers", "agents", "docker", "retry", "output", "git")


class RuntimeConfig:
    """运行时配置内存缓存（从 DB 加载，配置更新时刷新）"""

    _instance: "RuntimeConfig | None" = None

    def __init__(self) -> None:
        self.llm_providers: list[dict] = []
        self.agents_config: dict[str, Any] = {}
        self.docker_config: dict[str, Any] = {}
        self.retry_config: dict[str, Any] = {}
        self.output_config: dict[str, Any] = {}
        self.git_config: dict[str, Any] = {}

    @classmethod
    def get(cls) -> "RuntimeConfig":
        if cls._instance is None:
            cls._instance = RuntimeConfig()
        return cls._instance

    @classmethod
    def invalidate(cls) -> None:
        """配置变更后调用，使缓存失效（下次 get() 时重建）"""
        cls._instance = None

    def load_from_dict(self, data: dict[str, Any]) -> None:
        self.llm_providers = data.get("llm_providers", [])
        self.agents_config = data.get("agents", {})
        self.docker_config = data.get("docker", _defaults("docker"))
        self.retry_config = data.get("retry", _defaults("retry"))
        self.output_config = data.get("output", _defaults("output"))
        self.git_config = data.get("git", _defaults("git"))

    @property
    def max_retries(self) -> int:
        return self.retry_config.get("max_retries", 3)

    @property
    def output_base_dir(self) -> str:
        return self.output_config.get("base_dir", "projects")

    def get_llm_provider(self, provider_id: str) -> dict:
        for p in self.llm_providers:
            if p.get("id") == provider_id:
                return p
        return {}


async def load_runtime_config(session: AsyncSession) -> RuntimeConfig:
    """从 DB 加载配置并刷新 RuntimeConfig 单例，返回最新实例"""
    data = await get_full_config(session)
    RuntimeConfig.invalidate()
    rc = RuntimeConfig.get()
    rc.load_from_dict(data)
    return rc


async def get_full_config(session: AsyncSession) -> dict[str, Any]:
    """返回所有配置 section 合并后的 dict"""
    result = await session.execute(select(SystemConfig))
    rows = {row.key: row.value for row in result.scalars()}
    return {k: rows.get(k, _defaults(k)) for k in KEYS}


async def get_section(session: AsyncSession, key: str) -> Any:
    """获取单个配置 section"""
    row = await session.get(SystemConfig, key)
    return row.value if row else _defaults(key)


async def set_section(session: AsyncSession, key: str, value: Any) -> None:
    """写入单个配置 section（upsert）"""
    row = await session.get(SystemConfig, key)
    if row is None:
        row = SystemConfig(key=key)
        session.add(row)
    row.value = value


async def set_full_config(session: AsyncSession, data: dict[str, Any]) -> None:
    """全量写入配置（仅更新传入的 key）"""
    for k, v in data.items():
        if k in KEYS:
            await set_section(session, k, v)


async def seed_from_yaml(session: AsyncSession, yaml_path: str = "config.yaml") -> bool:
    """如果数据库尚无配置，从 config.yaml 导入；已有数据则跳过。返回是否执行了导入。"""
    # 检查是否已有数据
    result = await session.execute(select(SystemConfig).limit(1))
    if result.scalars().first() is not None:
        return False

    config_file = Path(yaml_path)
    if not config_file.exists():
        logger.warning("config.yaml 不存在，使用默认配置")
        data: dict = {}
    else:
        try:
            data = yaml.safe_load(config_file.read_text(encoding="utf-8")) or {}
        except Exception as e:
            logger.warning("读取 config.yaml 失败: %s，使用默认配置", e)
            data = {}

    for k in KEYS:
        if k in data:
            await set_section(session, k, data[k])
        else:
            await set_section(session, k, _defaults(k))

    logger.info("从 config.yaml 导入了配置到数据库")
    return True


def _defaults(key: str) -> Any:
    defaults: dict[str, Any] = {
        "llm_providers": [],
        "agents": {},
        "docker": {
            "mem_limit": "512m",
            "cpu_quota": 50000,
            "timeout_seconds": 120,
            "network_disabled": True,
        },
        "retry": {"max_retries": 3, "retry_delay": 2.0},
        "output": {"base_dir": "projects", "git_init": True},
        "git": {
            "enabled": False,
            "remote_url": "",
            "default_branch": "main",
            "auto_push": False,
        },
    }
    return defaults.get(key, {})

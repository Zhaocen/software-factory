from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from software_factory.db.models import Base

logger = logging.getLogger(__name__)

_engine = None
_AsyncSessionLocal: async_sessionmaker | None = None


def init_engine(db_url: str) -> None:
    """初始化数据库引擎（应在应用启动时调用一次）"""
    global _engine, _AsyncSessionLocal
    _engine = create_async_engine(
        db_url,
        echo=False,
        pool_recycle=3600,
        pool_pre_ping=True,
        pool_size=10,
        max_overflow=20,
    )
    _AsyncSessionLocal = async_sessionmaker(
        _engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    logger.info("Database engine initialized: %s", db_url.split("@")[-1])


async def create_tables() -> None:
    """自动建表（如果不存在则创建）"""
    if _engine is None:
        raise RuntimeError("Database engine not initialized")
    async with _engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("Database tables ready")


@asynccontextmanager
async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """获取数据库会话（上下文管理器，供后台任务使用）"""
    if _AsyncSessionLocal is None:
        raise RuntimeError("Database engine not initialized")
    async with _AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def db_session() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI 依赖注入用的 session 生成器"""
    if _AsyncSessionLocal is None:
        raise RuntimeError("Database engine not initialized")
    async with _AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise

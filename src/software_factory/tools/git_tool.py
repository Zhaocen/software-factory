from __future__ import annotations

import asyncio
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


async def init_repo(project_dir: str) -> None:
    """初始化 Git 仓库"""
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, _init_repo_sync, project_dir)


async def commit_all(project_dir: str, message: str) -> str:
    """提交所有变更，返回 commit hash"""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _commit_sync, project_dir, message)


def _init_repo_sync(project_dir: str) -> None:
    try:
        import git
        path = Path(project_dir)
        if not (path / ".git").exists():
            repo = git.Repo.init(path)
            logger.info("Git repo initialized at %s", project_dir)
    except Exception as e:
        logger.warning("Git init failed: %s", e)


def _commit_sync(project_dir: str, message: str) -> str:
    try:
        import git
        repo = git.Repo(project_dir)
        repo.git.add(A=True)
        if repo.is_dirty(untracked_files=True):
            commit = repo.index.commit(message)
            return commit.hexsha[:8]
        return "no-changes"
    except Exception as e:
        logger.warning("Git commit failed: %s", e)
        return "error"

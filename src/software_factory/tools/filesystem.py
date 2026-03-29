from __future__ import annotations

import aiofiles
from pathlib import Path


async def write_file(base_dir: str, relative_path: str, content: str) -> str:
    """将内容写入指定路径，自动创建父目录"""
    full_path = Path(base_dir) / relative_path
    full_path.parent.mkdir(parents=True, exist_ok=True)
    async with aiofiles.open(full_path, "w", encoding="utf-8") as f:
        await f.write(content)
    return str(full_path)


async def read_file(path: str) -> str:
    """读取文件内容"""
    async with aiofiles.open(path, "r", encoding="utf-8") as f:
        return await f.read()


async def ensure_dir(path: str) -> None:
    """确保目录存在"""
    Path(path).mkdir(parents=True, exist_ok=True)


def list_files(base_dir: str) -> list[str]:
    """列出目录下所有文件的相对路径"""
    base = Path(base_dir)
    if not base.exists():
        return []
    return [str(p.relative_to(base)) for p in base.rglob("*") if p.is_file()]

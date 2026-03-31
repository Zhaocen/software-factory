from __future__ import annotations

import shutil
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from software_factory.db.database import db_session
from software_factory.db.models import Project, ProjectLog
from software_factory.tools.filesystem import list_files

router = APIRouter(prefix="/api/projects", tags=["projects"])


@router.get("/", response_model=list[dict])
async def list_projects(session: AsyncSession = Depends(db_session)):
    """列出所有项目（按创建时间倒序）"""
    result = await session.execute(
        select(Project).order_by(Project.created_at.desc())
    )
    projects = result.scalars().all()
    return [p.to_dict() for p in projects]


@router.get("/{project_id}")
async def get_project(project_id: str, session: AsyncSession = Depends(db_session)):
    """获取项目详情（含各阶段交付件、文件列表）"""
    project = await session.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    data = project.to_dict()

    # 读取生成文件列表（从 workspace_path 目录）
    workspace = project.workspace_path
    if workspace and Path(workspace).exists():
        files = list_files(workspace)
        # 过滤隐藏文件
        data["files"] = [f for f in files if not Path(f).name.startswith(".")]
    else:
        data["files"] = []

    return data


@router.delete("/{project_id}", status_code=204)
async def delete_project(
    project_id: str,
    delete_files: bool = False,
    session: AsyncSession = Depends(db_session),
):
    """删除项目（可选是否同时删除磁盘文件）"""
    project = await session.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    # 可选删除磁盘文件
    if delete_files and project.workspace_path:
        workspace = Path(project.workspace_path)
        if workspace.exists():
            shutil.rmtree(workspace, ignore_errors=True)

    # 删除日志
    logs = await session.execute(
        select(ProjectLog).where(ProjectLog.project_id == project_id)
    )
    for log in logs.scalars().all():
        await session.delete(log)

    await session.delete(project)


@router.get("/{project_id}/logs")
async def get_project_logs(
    project_id: str,
    limit: int = 500,
    stage: str = "",
    session: AsyncSession = Depends(db_session),
):
    """获取项目运行日志，可按 stage 过滤"""
    project = await session.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    query = (
        select(ProjectLog)
        .where(ProjectLog.project_id == project_id)
        .order_by(ProjectLog.ts.asc())
        .limit(limit)
    )
    result = await session.execute(query)
    logs = result.scalars().all()

    log_dicts = [log.to_dict() for log in logs]

    # 按阶段过滤：保留该阶段的 stage_start/stage_end 以及所有 extra.stage 匹配的条目
    if stage:
        filtered = []
        for l in log_dicts:
            # type 中直接包含 stage 名
            if stage in (l.get("message") or ""):
                filtered.append(l)
                continue
            # extra 字段里有 stage 属性
            extra = l.get("extra") or {}
            if extra.get("stage") == stage or extra.get("node") == stage:
                filtered.append(l)
                continue
            # stage_start / stage_end 类型
            if l.get("type") in ("stage_start", "stage_end") and stage in (l.get("message") or ""):
                filtered.append(l)
        log_dicts = filtered

    return {"project_id": project_id, "logs": log_dicts}


@router.get("/{project_id}/files")
async def get_project_files(project_id: str, session: AsyncSession = Depends(db_session)):
    """获取项目文件列表"""
    project = await session.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    workspace = project.workspace_path
    if not workspace or not Path(workspace).exists():
        return {"project_id": project_id, "files": [], "workspace_path": workspace}

    files = list_files(workspace)
    files = [f for f in files if not Path(f).name.startswith(".")]
    return {"project_id": project_id, "files": files, "workspace_path": workspace}


@router.get("/{project_id}/file")
async def get_file_content(
    project_id: str,
    path: str,
    session: AsyncSession = Depends(db_session),
):
    """获取项目中特定文件的内容"""
    project = await session.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    workspace = project.workspace_path
    if not workspace:
        raise HTTPException(status_code=404, detail="No workspace path")

    file_path = Path(workspace) / path
    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(status_code=404, detail="File not found")

    # 安全检查：确保路径在 workspace 目录内
    try:
        file_path.resolve().relative_to(Path(workspace).resolve())
    except ValueError:
        raise HTTPException(status_code=403, detail="Access denied")

    return FileResponse(file_path)

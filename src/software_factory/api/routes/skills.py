from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from software_factory.db.database import db_session
from software_factory.db.models import Skill

router = APIRouter(prefix="/api/skills", tags=["skills"])


# ---- 数据模型 ----

class SkillCreate(BaseModel):
    name: str = Field(..., min_length=1)
    description: str = ""
    category: str = "general"
    content: str = ""
    is_active: bool = True


class SkillUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    category: str | None = None
    content: str | None = None
    is_active: bool | None = None


# ---- 路由 ----

@router.get("/", response_model=list[dict])
async def list_skills(
    category: str | None = None,
    active_only: bool = False,
    session: AsyncSession = Depends(db_session),
):
    """列出所有 Skills"""
    query = select(Skill).order_by(Skill.created_at.desc())
    if category:
        query = query.where(Skill.category == category)
    if active_only:
        query = query.where(Skill.is_active == True)  # noqa: E712

    result = await session.execute(query)
    return [s.to_dict() for s in result.scalars().all()]


@router.post("/", response_model=dict, status_code=201)
async def create_skill(body: SkillCreate, session: AsyncSession = Depends(db_session)):
    """创建新 Skill"""
    skill = Skill(
        id=str(uuid.uuid4()),
        name=body.name,
        description=body.description,
        category=body.category,
        content=body.content,
        is_active=body.is_active,
    )
    session.add(skill)
    await session.flush()
    await session.refresh(skill)
    return skill.to_dict()


@router.get("/{skill_id}", response_model=dict)
async def get_skill(skill_id: str, session: AsyncSession = Depends(db_session)):
    """获取单个 Skill"""
    skill = await session.get(Skill, skill_id)
    if not skill:
        raise HTTPException(status_code=404, detail="Skill not found")
    return skill.to_dict()


@router.put("/{skill_id}", response_model=dict)
async def update_skill(
    skill_id: str,
    body: SkillUpdate,
    session: AsyncSession = Depends(db_session),
):
    """更新 Skill"""
    skill = await session.get(Skill, skill_id)
    if not skill:
        raise HTTPException(status_code=404, detail="Skill not found")

    updates = body.model_dump(exclude_none=True)
    for k, v in updates.items():
        setattr(skill, k, v)
    skill.updated_at = datetime.now()

    await session.flush()
    await session.refresh(skill)
    return skill.to_dict()


@router.delete("/{skill_id}", status_code=204)
async def delete_skill(skill_id: str, session: AsyncSession = Depends(db_session)):
    """删除 Skill"""
    skill = await session.get(Skill, skill_id)
    if not skill:
        raise HTTPException(status_code=404, detail="Skill not found")
    await session.delete(skill)


@router.post("/import", response_model=list[dict], status_code=201)
async def import_skills(body: list[SkillCreate], session: AsyncSession = Depends(db_session)):
    """批量导入 Skills"""
    created = []
    for item in body:
        skill = Skill(
            id=str(uuid.uuid4()),
            name=item.name,
            description=item.description,
            category=item.category,
            content=item.content,
            is_active=item.is_active,
        )
        session.add(skill)
        created.append(skill)

    await session.flush()
    for s in created:
        await session.refresh(s)

    return [s.to_dict() for s in created]

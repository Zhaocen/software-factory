from __future__ import annotations

import json
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Project(Base):
    """项目信息表：存储项目元数据、状态、各阶段进度"""
    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str | None] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), default="building")  # building/completed/failed
    progress: Mapped[int] = mapped_column(Integer, default=0)
    current_stage: Mapped[str | None] = mapped_column(String(64))
    workspace_path: Mapped[str | None] = mapped_column(String(512))   # 用户选择的项目文件存储路径
    session_id: Mapped[str | None] = mapped_column(String(64))
    _stages_json: Mapped[str | None] = mapped_column("stages_json", Text)  # JSON 序列化的各阶段状态
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=func.now(), onupdate=func.now())

    @property
    def stages(self) -> dict:
        if self._stages_json:
            try:
                return json.loads(self._stages_json)
            except Exception:
                pass
        return {}

    @stages.setter
    def stages(self, value: dict) -> None:
        self._stages_json = json.dumps(value, ensure_ascii=False)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name or self.id,
            "description": self.description or "",
            "status": self.status,
            "progress": self.progress,
            "current_stage": self.current_stage or "",
            "workspace_path": self.workspace_path or "",
            "session_id": self.session_id,
            "stages": self.stages,
            "created_at": self.created_at.isoformat() if self.created_at else "",
            "updated_at": self.updated_at.isoformat() if self.updated_at else "",
        }


class Skill(Base):
    """Skills 表：存储可复用的知识/Prompt 模板"""
    __tablename__ = "skills"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    category: Mapped[str] = mapped_column(String(64), default="general")
    content: Mapped[str | None] = mapped_column(Text(length=2**24))  # MEDIUMTEXT
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=func.now(), onupdate=func.now())

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description or "",
            "category": self.category,
            "content": self.content or "",
            "is_active": self.is_active,
            "created_at": self.created_at.isoformat() if self.created_at else "",
            "updated_at": self.updated_at.isoformat() if self.updated_at else "",
        }


class ProjectLog(Base):
    """项目日志表：记录项目构建过程中的每一条日志"""
    __tablename__ = "project_logs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    project_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    log_type: Mapped[str | None] = mapped_column(String(32))
    message: Mapped[str | None] = mapped_column(Text)
    ts: Mapped[datetime] = mapped_column(DateTime, default=func.now(), index=True)
    extra_json: Mapped[str | None] = mapped_column(Text)  # 附加字段 JSON

    __table_args__ = (
        Index("idx_proj_ts", "project_id", "ts"),
    )

    def to_dict(self) -> dict:
        extra = {}
        if self.extra_json:
            try:
                extra = json.loads(self.extra_json)
            except Exception:
                pass
        return {
            "id": self.id,
            "project_id": self.project_id,
            "type": self.log_type,
            "message": self.message or "",
            "ts": self.ts.isoformat() if self.ts else "",
            **extra,
        }


class SystemConfig(Base):
    """系统配置表：以 key-value 形式存储所有配置（llm_providers / agents / docker 等）"""
    __tablename__ = "system_config"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value_json: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=func.now(), onupdate=func.now()
    )

    @property
    def value(self):
        return json.loads(self.value_json) if self.value_json else None

    @value.setter
    def value(self, v) -> None:
        self.value_json = json.dumps(v, ensure_ascii=False)

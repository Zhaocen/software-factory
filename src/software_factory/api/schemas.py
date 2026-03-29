from __future__ import annotations

from pydantic import BaseModel, Field


class StartRequest(BaseModel):
    description: str = Field(..., min_length=10, description="软件需求描述")
    workspace_path: str | None = Field(
        default=None,
        description="项目文件存储路径（绝对路径或相对路径），不填则自动生成",
    )


class StartResponse(BaseModel):
    session_id: str
    project_id: str
    workspace_path: str = ""
    message: str = "工厂已启动，请订阅 SSE 流获取实时进度"


class ClarifyRequest(BaseModel):
    answer: str = Field(..., min_length=1, description="用户对澄清问题的回答")


class ProjectSummary(BaseModel):
    project_id: str
    session_id: str
    stage: str
    workspace_path: str
    files: list[str] = []

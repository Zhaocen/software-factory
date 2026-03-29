from __future__ import annotations

import json
from typing import Any

from langchain_core.messages import AIMessage
from pydantic import BaseModel as PydanticModel, Field

from software_factory.agents.base import BaseAgent
from software_factory.state.factory_state import (
    APIEndpoint,
    ArchitectureArtifact,
    FactoryStage,
)


SYSTEM_PROMPT = """你是一名资深软件架构师。根据提供的需求文档，设计合理的系统架构。

设计原则：
1. 选择适合需求的技术栈（不过度工程化）
2. 清晰定义模块边界和 API 接口
3. 考虑可扩展性和可维护性
4. 生成清晰的目录结构说明

输出必须是有效的 JSON，符合指定的 schema。"""


class APIEndpointOutput(PydanticModel):
    method: str
    path: str
    description: str
    request_body: dict | None = None
    response_body: dict | None = None


class ArchitectureOutput(PydanticModel):
    model_config = {"extra": "ignore"}
    tech_stack: dict[str, str] = Field(default_factory=dict, description="技术栈，如 {backend: FastAPI, frontend: HTML}")
    system_components: list[str] = Field(default_factory=list, description="系统组件列表")
    api_endpoints: list[APIEndpointOutput] = Field(default_factory=list, description="API 接口列表")
    data_models: dict[str, Any] = Field(default_factory=dict, description="数据模型定义")
    directory_structure: str = Field(default="", description="目录结构的文本描述")
    architecture_notes: str = Field(default="", description="架构说明和设计决策")


class ArchitectureAgent(BaseAgent):
    agent_name = "architecture"
    skill_categories = ["architecture"]

    async def execute(self, state: dict) -> dict[str, Any]:
        requirements = state["requirements"]
        req_summary = f"""
项目名称：{requirements.project_name}
项目描述：{requirements.project_description}
功能需求：{json.dumps(requirements.functional_requirements, ensure_ascii=False)}
非功能需求：{json.dumps(requirements.non_functional_requirements, ensure_ascii=False)}
技术约束：{json.dumps(requirements.tech_constraints, ensure_ascii=False)}
"""

        # 加载相关 Skills
        skills_text, skill_names = await self._load_relevant_skills()

        from software_factory.tools.json_chain import create_json_chain

        chain = create_json_chain(self.llm, SYSTEM_PROMPT + skills_text, ArchitectureOutput)
        raw = await chain.ainvoke({"input": f"需求文档：\n{req_summary}\n\n请设计系统架构。"})
        result = ArchitectureOutput.model_validate(raw)

        api_endpoints = [
            APIEndpoint(
                method=ep.method,
                path=ep.path,
                description=ep.description,
                request_body=ep.request_body,
                response_body=ep.response_body,
            )
            for ep in result.api_endpoints
        ]

        artifact = ArchitectureArtifact(
            tech_stack=result.tech_stack,
            system_components=result.system_components,
            api_endpoints=api_endpoints,
            data_models=result.data_models,
            directory_structure=result.directory_structure,
            raw_text=result.architecture_notes,
        )

        progress_events: list[dict] = []
        if skill_names:
            progress_events.append({
                "type": "skills_applied",
                "stage": "architecture",
                "skills": skill_names,
                "message": f"应用技能参考：{', '.join(skill_names)}",
            })

        return {
            "current_stage": FactoryStage.UI_UX,
            "architecture": artifact,
            "stage_history": [FactoryStage.ARCHITECTURE],
            "progress_events": progress_events,
            "messages": [AIMessage(content=f"架构设计完成。技术栈：{json.dumps(result.tech_stack, ensure_ascii=False)}")],
        }

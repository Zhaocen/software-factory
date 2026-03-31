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

TOOL_PROMPT = """你是一名资深软件架构师。你有一组辅助工具可以使用，
请根据项目技术栈和需求自行判断是否需要调用工具及调用哪些工具，工具调用是可选的，按需使用即可。"""


class APIEndpointOutput(PydanticModel):
    method: str
    path: str
    description: str
    request_body: dict | list | None = None
    response_body: dict | list | None = None


class ArchitectureOutput(PydanticModel):
    model_config = {"extra": "ignore"}
    tech_stack: dict[str, str] = Field(
        default_factory=dict,
        description="技术栈，如 {backend: FastAPI, frontend: HTML}",
    )
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
        req_summary = (
            f"项目名称：{requirements.project_name}\n"
            f"项目描述：{requirements.project_description}\n"
            f"功能需求：{json.dumps(requirements.functional_requirements, ensure_ascii=False)}\n"
            "非功能需求："
            f"{json.dumps(requirements.non_functional_requirements, ensure_ascii=False)}\n"
            f"技术约束：{json.dumps(requirements.tech_constraints, ensure_ascii=False)}"
        )

        progress_events: list[dict] = []

        # ── 第一阶段：工具调用，获取架构设计最佳实践 ─────────────────────────────
        tools = self._get_skill_tools()
        tool_call_logs, tool_context = await self._run_with_tools(
            system_prompt=TOOL_PROMPT,
            user_msg=f"需求文档：\n{req_summary}",
            tools=tools,
        )

        if tool_call_logs:
            tool_names = list({inv["tool"] for inv in tool_call_logs})
            progress_events.append({
                "type": "skills_applied",
                "stage": "architecture",
                "skills": tool_names,
                "message": f"调用设计规范工具：{', '.join(tool_names)}",
                "tool_calls": tool_call_logs,
            })
            for inv in tool_call_logs:
                import logging as _l
                _l.getLogger(__name__).info(
                    "[ArchitectureAgent] tool=%s  result_preview=%s",
                    inv["tool"], inv["result"][:100],
                )

        # ── 第二阶段：结合工具结果生成架构 JSON ──────────────────────────────────
        # 加载 Skill 文本（作为额外提示补充）
        skills_text, skill_names = await self._load_relevant_skills()

        from software_factory.tools.json_chain import create_json_chain

        chain = create_json_chain(self.llm, SYSTEM_PROMPT + skills_text, ArchitectureOutput)
        user_input = (
            f"需求文档：\n{req_summary}"
            + tool_context  # 追加工具结果上下文
            + "\n\n请基于以上信息设计系统架构。"
        )
        raw = await chain.ainvoke({"input": user_input})
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

        if skill_names and not tool_call_logs:
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
            "messages": [AIMessage(
                content=f"架构设计完成。技术栈：{json.dumps(result.tech_stack, ensure_ascii=False)}"
            )],
        }

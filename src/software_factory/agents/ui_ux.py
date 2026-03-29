from __future__ import annotations

import json
from typing import Any

from langchain_core.messages import AIMessage
from pydantic import BaseModel as PydanticModel, Field

from software_factory.agents.base import BaseAgent
from software_factory.state.factory_state import (
    FactoryStage,
    UIComponent,
    UIUXArtifact,
)


SYSTEM_PROMPT = """你是一名 UI/UX 设计师。根据需求和架构文档，设计用户界面和交互流程。

输出内容：
1. 页面列表和每个页面的功能描述
2. 关键 UI 组件清单
3. 用户操作流程（文字描述）
4. 设计规范（颜色、字体等）

保持简洁实用，输出 JSON 格式。"""


class UIComponentOutput(PydanticModel):
    name: str
    page: str
    description: str
    interactions: list[str]


class UIUXOutput(PydanticModel):
    model_config = {"extra": "ignore"}
    pages: list[dict[str, str]] = Field(default_factory=list, description="页面列表，每项含 name 和 description")
    components: list[UIComponentOutput] = Field(default_factory=list, description="UI 组件列表")
    user_flows: list[str] = Field(default_factory=list, description="用户操作流程描述")
    design_tokens: dict[str, str] = Field(default_factory=dict, description="设计规范（primary_color、font_family 等）")
    design_notes: str = Field(default="", description="设计说明")


class UIUXAgent(BaseAgent):
    agent_name = "ui_ux"

    async def execute(self, state: dict) -> dict[str, Any]:
        requirements = state["requirements"]
        architecture = state["architecture"]

        context = f"""
项目：{requirements.project_name}
功能需求：{json.dumps(requirements.functional_requirements[:5], ensure_ascii=False)}
技术栈：{json.dumps(architecture.tech_stack, ensure_ascii=False)}
系统组件：{json.dumps(architecture.system_components[:8], ensure_ascii=False)}
"""

        from software_factory.tools.json_chain import create_json_chain

        chain = create_json_chain(self.llm, SYSTEM_PROMPT, UIUXOutput)
        raw = await chain.ainvoke({"input": f"项目信息：\n{context}\n\n请设计 UI/UX 方案。"})
        result = UIUXOutput.model_validate(raw)

        components = [
            UIComponent(
                name=c.name,
                page=c.page,
                description=c.description,
                interactions=c.interactions,
            )
            for c in result.components
        ]

        artifact = UIUXArtifact(
            pages=result.pages,
            components=components,
            user_flows=result.user_flows,
            design_tokens=result.design_tokens,
            raw_text=result.design_notes,
        )

        return {
            "current_stage": FactoryStage.CODING,
            "ui_ux": artifact,
            "stage_history": [FactoryStage.UI_UX],
            "messages": [AIMessage(content=f"UI/UX 设计完成。共 {len(result.pages)} 个页面，{len(components)} 个组件。")],
        }

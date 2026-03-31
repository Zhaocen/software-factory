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

TOOL_PROMPT = """你是一名 UI/UX 设计师。你有一组辅助工具可以使用，
请根据项目类型自行判断是否需要调用工具及调用哪些工具，工具调用是可选的，按需使用即可。"""


class UIComponentOutput(PydanticModel):
    name: str
    page: str
    description: str
    interactions: list[str]


class UIUXOutput(PydanticModel):
    model_config = {"extra": "ignore"}
    pages: list[dict[str, str]] = Field(
        default_factory=list,
        description="页面列表，每项含 name 和 description",
    )
    components: list[UIComponentOutput] = Field(default_factory=list, description="UI 组件列表")
    user_flows: list[str] = Field(default_factory=list, description="用户操作流程描述")
    design_tokens: dict[str, str] = Field(
        default_factory=dict,
        description="设计规范（primary_color、font_family 等）",
    )
    design_notes: str = Field(default="", description="设计说明")


class UIUXAgent(BaseAgent):
    agent_name = "ui_ux"
    skill_categories = ["ui_ux"]

    async def execute(self, state: dict) -> dict[str, Any]:
        requirements = state["requirements"]
        architecture = state["architecture"]

        # 判断应用类型，用于工具参数
        tech_str = json.dumps(architecture.tech_stack).lower()
        if any(kw in tech_str for kw in ["cli", "command", "terminal", "argparse", "typer"]):
            app_type = "cli"
        elif not any(kw in tech_str for kw in ["html", "react", "vue", "frontend", "前端", "web"]):
            app_type = "api"
        else:
            app_type = "web"

        context = (
            f"项目：{requirements.project_name}\n"
            f"功能需求：{json.dumps(requirements.functional_requirements[:5], ensure_ascii=False)}\n"
            f"技术栈：{json.dumps(architecture.tech_stack, ensure_ascii=False)}\n"
            f"系统组件：{json.dumps(architecture.system_components[:8], ensure_ascii=False)}\n"
            f"应用类型：{app_type}"
        )

        progress_events: list[dict] = []

        # ── 第一阶段：工具调用 — 获取 UI 设计模式 + 配色规范 ─────────────────────
        tools = self._get_skill_tools()
        tool_call_logs, tool_context = await self._run_with_tools(
            system_prompt=TOOL_PROMPT,
            user_msg=context,
            tools=tools,
            max_rounds=3,
        )

        if tool_call_logs:
            tool_names = list({inv["tool"] for inv in tool_call_logs})
            progress_events.append({
                "type": "skills_applied",
                "stage": "ui_ux",
                "skills": tool_names,
                "message": f"调用 UI 设计规范工具：{', '.join(tool_names)}",
                "tool_calls": tool_call_logs,
            })
            import logging as _l
            for inv in tool_call_logs:
                _l.getLogger(__name__).info(
                    "[UIUXAgent] tool=%s  result_preview=%s",
                    inv["tool"], inv["result"][:100],
                )

        # ── 第二阶段：LLM 生成 UI/UX 方案 ──────────────────────────────────────
        from software_factory.tools.json_chain import create_json_chain

        chain = create_json_chain(self.llm, SYSTEM_PROMPT, UIUXOutput)
        user_msg = (
            f"项目信息：\n{context}"
            + tool_context
            + "\n\n请基于以上信息设计 UI/UX 方案。"
        )
        raw = await chain.ainvoke({"input": user_msg})
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
            "progress_events": progress_events,
            "messages": [AIMessage(
                content=(
                    f"UI/UX 设计完成。共 {len(result.pages)} 个页面，"
                    f"{len(components)} 个组件。"
                )
            )],
        }

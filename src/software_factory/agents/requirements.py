from __future__ import annotations

import uuid
from typing import Any

from langchain_core.messages import AIMessage
from pydantic import BaseModel as PydanticModel
from pydantic import Field

from software_factory.agents.base import BaseAgent
from software_factory.state.factory_state import (
    FactoryStage,
    RequirementsArtifact,
    UserStory,
)

SYSTEM_PROMPT = """你是一名专业的产品需求分析师。你的任务是将用户的模糊描述转化为清晰的结构化需求文档。

分析时请注意：
1. 提取核心功能需求，写成用户故事格式："作为[用户]，我想要[功能]，以便[价值]"
2. 识别非功能需求（性能、安全、可用性等）
3. 明确技术约束和范围外功能
4. 如果描述过于模糊，提出最多3个澄清问题

输出必须是有效的 JSON，符合指定的 schema。"""

TOOL_PROMPT = """你是一名专业的产品需求分析师。你有一组辅助工具可以使用，
请根据任务需要自行判断是否调用以及调用哪些工具，工具调用是可选的，按需使用即可。"""


class UserStoryOutput(PydanticModel):
    id: str
    title: str
    description: str
    acceptance_criteria: list[str]
    priority: str = "medium"


class RequirementsOutput(PydanticModel):
    model_config = {"extra": "ignore"}
    project_name: str = Field(description="项目名称")
    project_description: str = Field(default="", description="项目简述（2-3句话）")
    user_stories: list[UserStoryOutput] = Field(default_factory=list)
    functional_requirements: list[str] = Field(default_factory=list)
    non_functional_requirements: list[str] = Field(default_factory=list)
    tech_constraints: list[str] = Field(default_factory=list)
    out_of_scope: list[str] = Field(default_factory=list)
    needs_clarification: bool = Field(default=False)
    clarification_questions: list[str] = Field(default_factory=list)


class RequirementsAgent(BaseAgent):
    agent_name = "requirements"
    skill_categories = ["requirements"]

    async def execute(self, state: "dict") -> dict[str, Any]:
        user_input = state["user_input"]
        progress_events: list[dict] = []

        # ── 第一阶段：工具调用 — 分析需求完整性 + 获取用户故事模板 ──────────────
        tools = self._get_skill_tools()
        tool_call_logs, tool_context = await self._run_with_tools(
            system_prompt=TOOL_PROMPT,
            user_msg=f"用户需求描述：{user_input}",
            tools=tools,
            max_rounds=3,
        )

        if tool_call_logs:
            tool_names = list({inv["tool"] for inv in tool_call_logs})
            progress_events.append(
                {
                    "type": "skills_applied",
                    "stage": "requirements",
                    "skills": tool_names,
                    "message": f"调用需求分析工具：{', '.join(tool_names)}",
                    "tool_calls": tool_call_logs,
                }
            )
            for inv in tool_call_logs:
                import logging as _l

                _l.getLogger(__name__).info(
                    "[RequirementsAgent] tool=%s  result=%s",
                    inv["tool"],
                    inv["result"][:150],
                )

        # ── 第二阶段：LLM 生成结构化需求 JSON ────────────────────────────────────
        from software_factory.tools.json_chain import create_json_chain

        # tool_context 已在 base._run_with_tools 中转义花括号
        system = SYSTEM_PROMPT
        if tool_context:
            system = system + tool_context

        chain = create_json_chain(
            self.llm,
            system + "\n\n用户需求描述：\n{input}",
            RequirementsOutput,
        )
        raw = await chain.ainvoke({"input": user_input})
        result = RequirementsOutput.model_validate(raw)

        # 如需澄清且未超过澄清轮次限制
        if result.needs_clarification and state.get("clarification_rounds", 0) < 2:
            questions = "\n".join(
                f"{i + 1}. {q}" for i, q in enumerate(result.clarification_questions)
            )
            clarify_msg = f"在开始设计之前，我需要了解几个问题：\n\n{questions}"
            return {
                "current_stage": FactoryStage.CLARIFYING,
                "clarification_rounds": state.get("clarification_rounds", 0) + 1,
                "messages": [AIMessage(content=clarify_msg)],
                "progress_events": progress_events
                + [
                    {
                        "type": "clarify_needed",
                        "stage": "requirements",
                        "questions": result.clarification_questions,
                        "message": clarify_msg,
                    }
                ],
            }

        user_stories = [
            UserStory(
                id=s.id or str(uuid.uuid4())[:8],
                title=s.title,
                description=s.description,
                acceptance_criteria=s.acceptance_criteria,
                priority=s.priority,  # type: ignore[arg-type]
            )
            for s in result.user_stories
        ]

        artifact = RequirementsArtifact(
            project_name=result.project_name,
            project_description=result.project_description,
            user_stories=user_stories,
            functional_requirements=result.functional_requirements,
            non_functional_requirements=result.non_functional_requirements,
            tech_constraints=result.tech_constraints,
            out_of_scope=result.out_of_scope,
        )

        return {
            "current_stage": FactoryStage.ARCHITECTURE,
            "requirements": artifact,
            "stage_history": [FactoryStage.REQUIREMENTS],
            "progress_events": progress_events,
            "messages": [
                AIMessage(
                    content=(
                        f"需求分析完成。项目：{artifact.project_name}\n"
                        f"共 {len(user_stories)} 个用户故事。"
                    )
                )
            ],
        }

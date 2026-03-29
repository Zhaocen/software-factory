from __future__ import annotations

import uuid
from typing import Any

from langchain_core.messages import AIMessage
from pydantic import BaseModel as PydanticModel, Field

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
    user_stories: list[UserStoryOutput] = Field(default_factory=list, description="用户故事列表")
    functional_requirements: list[str] = Field(default_factory=list, description="功能需求列表")
    non_functional_requirements: list[str] = Field(default_factory=list, description="非功能需求列表")
    tech_constraints: list[str] = Field(default_factory=list, description="技术约束列表")
    out_of_scope: list[str] = Field(default_factory=list, description="范围外功能列表")
    needs_clarification: bool = Field(default=False, description="是否需要进一步澄清")
    clarification_questions: list[str] = Field(default_factory=list, description="澄清问题列表（最多3个）")


class RequirementsAgent(BaseAgent):
    agent_name = "requirements"

    async def execute(self, state: "dict") -> dict[str, Any]:
        from software_factory.tools.json_chain import create_json_chain

        chain = create_json_chain(
            self.llm,
            SYSTEM_PROMPT + "\n\n用户需求描述：\n{input}",
            RequirementsOutput,
        )
        # create_json_chain 使用 {input} 作为 human 消息
        raw = await chain.ainvoke({"input": state["user_input"]})
        result = RequirementsOutput.model_validate(raw)

        # 如需澄清且未超过澄清轮次限制
        if result.needs_clarification and state.get("clarification_rounds", 0) < 2:
            questions = "\n".join(
                f"{i+1}. {q}" for i, q in enumerate(result.clarification_questions)
            )
            clarify_msg = f"在开始设计之前，我需要了解几个问题：\n\n{questions}"
            return {
                "current_stage": FactoryStage.CLARIFYING,
                "clarification_rounds": state.get("clarification_rounds", 0) + 1,
                "messages": [AIMessage(content=clarify_msg)],
                "progress_events": [{
                    "type": "clarify_needed",
                    "stage": "requirements",
                    "questions": result.clarification_questions,
                    "message": clarify_msg,
                }],
            }

        # 转换为内部 Artifact
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
            "messages": [AIMessage(content=f"需求分析完成。项目：{artifact.project_name}\n共 {len(user_stories)} 个用户故事。")],
        }

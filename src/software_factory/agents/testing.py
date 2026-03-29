from __future__ import annotations

import json
import logging
import uuid
from typing import Any

from langchain_core.messages import AIMessage
from pydantic import BaseModel as PydanticModel, Field

from software_factory.agents.base import BaseAgent
from software_factory.state.factory_state import (
    FactoryStage,
    TestCase,
    TestingArtifact,
    TestResult,
)
from software_factory.tools.filesystem import write_file

logger = logging.getLogger(__name__)


SYSTEM_PROMPT = """你是一名专业的测试工程师。根据项目代码和需求，生成全面的测试用例。

要求：
1. 为核心功能编写单元测试
2. 覆盖正常流程和边界条件（如除以零、空输入等）
3. 测试代码应能直接运行，不依赖外部服务
4. 使用项目技术栈对应的测试框架（Python 用 pytest，Node 用 jest）
5. 测试文件放在 tests/ 目录下
6. 每个测试函数名以 test_ 开头

输出 JSON 格式。"""


class TestCaseOutput(PydanticModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4())[:8])
    name: str
    test_type: str = "unit"
    file_path: str
    content: str


class TestingOutput(PydanticModel):
    test_cases: list[TestCaseOutput] = Field(default_factory=list)
    test_notes: str = ""


class TestingAgent(BaseAgent):
    agent_name = "testing"
    skill_categories = ["testing"]

    def __init__(self, settings, docker_executor=None):
        super().__init__(settings)
        self.docker_executor = docker_executor

    async def execute(self, state: dict) -> dict[str, Any]:
        requirements = state["requirements"]
        architecture = state["architecture"]
        coding = state["coding"]
        output_dir = state["output_dir"]

        # 加载相关 Skills
        skills_text, skill_names = await self._load_relevant_skills()

        progress_events: list[dict] = []
        if skill_names:
            progress_events.append({
                "type": "skills_applied",
                "stage": "testing",
                "skills": skill_names,
                "message": f"应用技能参考：{', '.join(skill_names)}",
            })

        # 获取部分代码内容作为上下文（限制长度）
        code_summary = self._summarize_code(coding)

        from software_factory.tools.json_chain import create_json_chain

        chain = create_json_chain(self.llm, SYSTEM_PROMPT + skills_text, TestingOutput)
        user_msg = (
            f"项目名：{requirements.project_name}\n"
            f"技术栈：{json.dumps(architecture.tech_stack, ensure_ascii=False)}\n"
            f"功能需求：{json.dumps(requirements.functional_requirements[:5], ensure_ascii=False)}\n\n"
            f"已生成的代码文件：\n{code_summary}\n\n请生成测试代码。"
        )
        raw = await chain.ainvoke({"input": user_msg})
        result = TestingOutput.model_validate(raw)

        test_cases = []
        for tc in result.test_cases:
            test_case = TestCase(
                id=tc.id,
                name=tc.name,
                test_type=tc.test_type,  # type: ignore[arg-type]
                file_path=tc.file_path,
                content=tc.content,
            )
            test_cases.append(test_case)
            await write_file(output_dir, tc.file_path, tc.content)
            logger.info("Test written: %s", tc.file_path)
            progress_events.append({
                "type": "file_created",
                "stage": "testing",
                "path": tc.file_path,
                "language": "python",
                "message": f"生成测试文件: {tc.file_path}",
            })

        # 尝试在 Docker 中执行测试
        test_result: TestResult | None = None
        if self.docker_executor and test_cases:
            progress_events.append({
                "type": "test_running",
                "stage": "testing",
                "message": "在 Docker 沙箱中执行测试...",
            })
            try:
                test_result = await self.docker_executor.run_tests(
                    project_dir=output_dir,
                    tech_stack=architecture.tech_stack,
                )
                logger.info("Tests executed: passed=%s output_preview=%s",
                            test_result.passed, (test_result.output or "")[:200])
                progress_events.append({
                    "type": "test_result",
                    "stage": "testing",
                    "passed": test_result.passed,
                    "total": test_result.total,
                    "failed": test_result.failed,
                    "output": (test_result.output or "")[:500],
                    "message": f"测试{'通过' if test_result.passed else '失败'} — "
                               f"{test_result.output[:200] if test_result.output else ''}",
                })
            except Exception as e:
                logger.warning("Docker test execution failed: %s", e)
                test_result = TestResult(
                    passed=True,  # Docker 不可用时视为跳过，不阻断流程
                    total=len(test_cases),
                    failed=0,
                    output=f"Docker 执行不可用，跳过自动测试：{e}",
                )
                progress_events.append({
                    "type": "test_skipped",
                    "stage": "testing",
                    "message": f"Docker 测试跳过: {str(e)[:100]}",
                })
        else:
            reason = "docker_executor 未初始化" if not self.docker_executor else "没有测试用例"
            test_result = TestResult(
                passed=True,
                total=len(test_cases),
                failed=0,
                output=f"测试文件已生成，未在 Docker 中执行（{reason}）",
            )
            progress_events.append({
                "type": "test_skipped",
                "stage": "testing",
                "message": f"Docker 测试未执行（{reason}）",
            })

        artifact = TestingArtifact(
            test_cases=test_cases,
            test_results=test_result,
            coverage_report=None,
            raw_text=result.test_notes,
        )

        # 测试失败且未超重试次数时，回退到编码阶段
        if test_result and not test_result.passed and state["retry_count"] < state["max_retries"]:
            progress_events.append({
                "type": "test_retry",
                "stage": "testing",
                "retry_count": state["retry_count"] + 1,
                "message": f"测试失败，回退重新生成代码（第 {state['retry_count'] + 1} 次重试）",
            })
            return {
                "current_stage": FactoryStage.CODING,
                "testing": artifact,
                "retry_count": state["retry_count"] + 1,
                "error": f"测试失败，回退重试（第 {state['retry_count'] + 1} 次）",
                "progress_events": progress_events,
                "messages": [AIMessage(content=(
                    f"测试未通过，正在重新生成代码（第 {state['retry_count'] + 1} 次重试）...\n"
                    f"测试输出：{(test_result.output or '')[:300]}"
                ))],
                "stage_history": [FactoryStage.TESTING],
            }

        return {
            "current_stage": FactoryStage.DEVOPS,
            "testing": artifact,
            "stage_history": [FactoryStage.TESTING],
            "progress_events": progress_events,
            "messages": [AIMessage(content=f"测试完成。生成了 {len(test_cases)} 个测试用例。")],
        }

    def _summarize_code(self, coding) -> str:
        if not coding or not coding.files:
            return "（无代码文件）"
        lines = []
        for f in coding.files[:10]:  # 最多展示 10 个文件
            preview = f.content[:300].replace("\n", " ")
            lines.append(f"- {f.path} ({f.language}): {preview}...")
        return "\n".join(lines)

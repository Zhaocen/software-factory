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


SYSTEM_PROMPT = """你是一名专业的测试工程师。根据项目代码和需求，生成能真正运行并验证功能正确性的测试用例。

严格要求：
1. 必须直接 import 源码模块进行测试，例如 `from calculator import add, subtract`
2. 测试必须覆盖所有核心功能，每个函数至少 2-3 个测试用例
3. 必须覆盖边界条件（如除以零、空输入、负数、None 等）
4. 测试代码不能依赖外部服务、数据库、文件系统（除非项目本身是文件操作工具）
5. 使用 pytest，测试函数名以 test_ 开头
6. 测试文件放在 tests/ 目录，文件名以 test_ 开头
7. tests/ 目录下必须有 __init__.py 文件（内容为空即可）
8. import 路径必须正确，若源码在根目录则直接 import，若在 src/ 则用 `sys.path.insert(0, 'src')`
9. 每个 assert 语句必须有明确的期望值，禁止只写 `assert result` 这种无意义断言

除了测试用例，还必须在输出 JSON 中提供执行环境信息：
- docker_image：运行测试所需的 Docker 镜像全名
- install_command：安装依赖的完整 shell 命令
- test_command：运行测试的完整 shell 命令

输出 JSON 格式，包含 test_cases、docker_image、install_command、test_command 字段。"""


class TestCaseOutput(PydanticModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4())[:8])
    name: str
    test_type: str = "unit"
    file_path: str
    content: str


class TestingOutput(PydanticModel):
    test_cases: list[TestCaseOutput] = Field(default_factory=list)
    test_notes: str = ""
    docker_image: str = Field(
        default="",
        description="运行测试用的 Docker 镜像，如 python:3.11-slim、node:18-alpine",
    )
    install_command: str = Field(
        default="",
        description="安装依赖的 shell 命令，如 pip install -r requirements.txt",
    )
    test_command: str = Field(
        default="",
        description="运行测试的 shell 命令，如 python -m pytest tests/ -v --tb=long",
    )


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

        progress_events: list[dict] = []

        # ── 第一阶段：_run_with_tools 驱动 — 语法检查 + 测试规范 ──────────────────
        tools = self._get_skill_tools()

        # 构建源码文件列表，让 LLM 决定对哪些文件调用 check_python_syntax
        source_files_info = [
            f.path for f in (coding.files or [])
            if f.path.endswith(".py") and not f.path.startswith("tests/")
        ][:8]

        source_snippets = "\n\n".join(
            f"文件 {f.path}:\n```python\n{f.content[:500]}\n```"
            for f in (coding.files or [])
            if f.path.endswith(".py") and not f.path.startswith("tests/")
        )[:3000]

        tool_call_logs, tool_context = await self._run_with_tools(
            system_prompt=(
                "你是一名测试工程师，你有一组辅助工具可以使用，"
                "请根据实际情况自行判断是否需要调用工具及调用哪些工具，按需使用即可。"
            ),
            user_msg=(
                f"待测试的 Python 源码文件列表：{source_files_info}\n\n"
                f"{source_snippets}"
            ),
            tools=tools,
            max_rounds=len(source_files_info) + 2,
        )

        if tool_call_logs:
            tool_names = list({inv["tool"] for inv in tool_call_logs})
            progress_events.append({
                "type": "skills_applied",
                "stage": "testing",
                "skills": tool_names,
                "message": f"调用测试规范工具：{', '.join(tool_names)}",
                "tool_calls": tool_call_logs,
            })

        # 加载 Skill 文本（兼容文本注入）
        skills_text, skill_names = await self._load_relevant_skills()
        if skill_names and not tool_call_logs:
            progress_events.append({
                "type": "skills_applied",
                "stage": "testing",
                "skills": skill_names,
                "message": f"应用技能参考：{', '.join(skill_names)}",
            })

        # ── 第二阶段：LLM 生成测试用例 ──────────────────────────────────────────
        code_summary = self._summarize_code(coding)

        from software_factory.tools.json_chain import create_json_chain

        chain = create_json_chain(self.llm, SYSTEM_PROMPT + skills_text, TestingOutput)
        user_msg = (
            f"项目名：{requirements.project_name}\n"
            f"技术栈：{json.dumps(architecture.tech_stack, ensure_ascii=False)}\n"
            f"功能需求：{json.dumps(requirements.functional_requirements[:5], ensure_ascii=False)}\n\n"
            f"已生成的代码文件：\n{code_summary}"
            + tool_context
            + "\n\n请生成测试代码。"
        )
        raw = await chain.ainvoke({"input": user_msg})
        result = TestingOutput.model_validate(raw)

        # ── 写入测试文件 ──────────────────────────────────────────────────────────
        test_cases = []
        has_tests_dir = False
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
            if tc.file_path.startswith("tests/"):
                has_tests_dir = True
            logger.info("Test written: %s", tc.file_path)

        if has_tests_dir:
            await write_file(output_dir, "tests/__init__.py", "")
            progress_events.append({
                "type": "file_created",
                "stage": "testing",
                "path": "tests/__init__.py",
                "language": "python",
                "message": "生成测试文件: tests/__init__.py",
            })

        for tc in result.test_cases:
            progress_events.append({
                "type": "file_created",
                "stage": "testing",
                "path": tc.file_path,
                "language": "python",
                "message": f"生成测试文件: {tc.file_path}",
            })

        # ── 第三阶段：_run_with_tools 对测试文件做语法检查 ───────────────────────
        await self._check_test_files_via_tools(result.test_cases, progress_events)

        # ── 第四阶段：Docker 沙箱执行测试 ────────────────────────────────────────
        test_result: TestResult | None = None
        if self.docker_executor and test_cases:
            docker_image = result.docker_image or ""
            install_cmd = result.install_command or ""
            test_cmd = result.test_command or ""
            progress_events.append({
                "type": "test_running",
                "stage": "testing",
                "message": (
                    f"在 Docker 沙箱中执行测试"
                    f"（镜像: {docker_image or '自动推断'}）..."
                ),
            })
            try:
                test_result = await self.docker_executor.run_tests(
                    project_dir=output_dir,
                    tech_stack=architecture.tech_stack,
                    docker_image=docker_image,
                    install_command=install_cmd,
                    test_command=test_cmd,
                )
                logger.info(
                    "Tests executed: passed=%s output_preview=%s",
                    test_result.passed, (test_result.output or "")[:200],
                )
                progress_events.append({
                    "type": "test_result",
                    "stage": "testing",
                    "passed": test_result.passed,
                    "total": test_result.total,
                    "failed": test_result.failed,
                    "output": (test_result.output or "")[:500],
                    "message": (
                        f"测试{'通过' if test_result.passed else '失败'} — "
                        f"{test_result.output[:200] if test_result.output else ''}"
                    ),
                })
            except Exception as e:
                logger.warning("Docker test execution failed: %s", e)
                test_result = TestResult(
                    passed=True,
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
            error_output = test_result.output or ""
            coding_files = state.get("coding") and state["coding"].files or []
            source_files = [
                {"path": f.path, "content": f.content}
                for f in coding_files
                if f.path.endswith(".py") and not f.path.startswith("tests/")
            ][:10]
            fix_context = {
                "error_output": error_output[:3000],
                "failed_files": source_files,
            }

            progress_events.append({
                "type": "test_retry",
                "stage": "testing",
                "retry_count": state["retry_count"] + 1,
                "message": (
                    f"测试失败，自动反思修复代码（第 {state['retry_count'] + 1} 次重试）"
                ),
            })
            return {
                "current_stage": FactoryStage.CODING,
                "testing": artifact,
                "retry_count": state["retry_count"] + 1,
                "fix_context": fix_context,
                "error": f"测试失败，回退重试（第 {state['retry_count'] + 1} 次）",
                "progress_events": progress_events,
                "messages": [AIMessage(content=(
                    f"测试未通过，正在自动分析错误并修复代码"
                    f"（第 {state['retry_count'] + 1} 次重试）...\n"
                    f"测试输出：{(test_result.output or '')[:300]}"
                ))],
                "stage_history": [FactoryStage.TESTING],
            }

        return {
            "current_stage": FactoryStage.DEVOPS,
            "testing": artifact,
            "stage_history": [FactoryStage.TESTING],
            "progress_events": progress_events,
            "messages": [AIMessage(
                content=f"测试完成。生成了 {len(test_cases)} 个测试用例。"
            )],
        }

    # ── 工具辅助：对生成的测试文件做语法检查（走 _run_with_tools）──────────────

    async def _check_test_files_via_tools(
        self,
        test_cases: list[TestCaseOutput],
        progress_events: list[dict],
    ) -> None:
        """通过 _run_with_tools 调用 check_python_syntax 验证测试文件语法"""
        py_cases = [tc for tc in test_cases if tc.file_path.endswith(".py")]
        if not py_cases:
            return

        tools = self._get_skill_tools()
        file_snippets = "\n\n".join(
            f"文件 {tc.file_path}:\n```python\n{tc.content[:400]}\n```"
            for tc in py_cases
        )

        logs, _ = await self._run_with_tools(
            system_prompt=(
                "你是一名测试工程师，你有一组辅助工具可以使用，"
                "请根据实际情况自行判断是否调用工具及调用哪些工具，按需使用即可。"
            ),
            user_msg=f"以下是刚生成的测试文件，请按需检查：\n\n{file_snippets}",
            tools=tools,
            max_rounds=len(py_cases) + 2,
        )

        errors = [
            inv for inv in logs
            if "语法错误" in inv["result"] or "SyntaxError" in inv["result"]
        ]

        if errors:
            err_files = [inv["args"].get("file_name", "?") for inv in errors]
            progress_events.append({
                "type": "syntax_error_found",
                "stage": "testing",
                "files": err_files,
                "tool_calls": errors,
                "message": f"测试文件语法检查发现问题：{', '.join(err_files)}",
            })
        else:
            progress_events.append({
                "type": "syntax_fixed",
                "stage": "testing",
                "files": [tc.file_path for tc in py_cases],
                "tool_calls": logs,
                "message": "所有测试文件语法检查通过 ✓",
            })

    def _summarize_code(self, coding) -> str:
        """传递完整源码内容（非预览），让 LLM 能生成正确的 import 路径和断言"""
        if not coding or not coding.files:
            return "（无代码文件）"
        lines = []
        total_len = 0
        skip_patterns = [
            "test_", "requirements", "README", ".env",
            "Dockerfile", ".yml", ".yaml", ".md",
        ]
        for f in coding.files:
            if any(p in f.path for p in skip_patterns):
                continue
            if total_len > 8000:
                lines.append("# ... 更多文件已省略（已超出长度限制）")
                break
            lines.append(f"### 文件: {f.path} ({f.language})")
            lines.append(f"```{f.language}")
            lines.append(f.content)
            lines.append("```")
            lines.append("")
            total_len += len(f.content)
        return "\n".join(lines) if lines else "（无源码文件）"

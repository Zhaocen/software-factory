from __future__ import annotations

import ast
import json
import logging
from typing import Any

from langchain_core.messages import AIMessage
from pydantic import BaseModel as PydanticModel, Field

from software_factory.agents.base import BaseAgent
from software_factory.state.factory_state import (
    CodeFile,
    CodingArtifact,
    FactoryStage,
)
from software_factory.tools.filesystem import write_file

logger = logging.getLogger(__name__)


SYSTEM_PROMPT = """你是一名专业的全栈开发工程师。根据需求文档、架构设计和 UI/UX 规范，生成高质量的代码。

代码要求：
1. 代码结构清晰，有必要的注释
2. 遵循所选技术栈的最佳实践
3. 包含基本的错误处理
4. 每次只生成指定模块的代码
5. 对于简单的 Python 脚本项目，直接生成可运行的 .py 文件，不要引入不必要的框架

输出 JSON 格式，包含文件路径和代码内容。"""

FIX_SYSTEM_PROMPT = """你是一名专业的代码调试工程师。你需要分析错误信息，找到问题根因并修复代码。

修复要求：
1. 仔细阅读错误信息，定位具体出错的文件和行号
2. 只修改有问题的文件，不要改动正确的文件
3. 修复后的代码必须能通过所有测试
4. 保持代码风格和原有逻辑不变，只修复错误

输出 JSON 格式，只包含需要修改的文件。"""

REFLECT_SYSTEM_PROMPT = """你是一名代码审查专家。以下代码存在语法错误，请修复它。

要求：
1. 保持文件路径不变
2. 修复所有语法错误
3. 不要改变代码的业务逻辑
4. 输出完整的修复后文件内容

输出 JSON 格式。"""


class CodeFileOutput(PydanticModel):
    model_config = {"extra": "ignore"}
    path: str = Field(description="相对于项目根目录的文件路径")
    content: str = Field(description="完整的文件内容")
    language: str = Field(default="text", description="编程语言，如 python、javascript、html")
    description: str = Field(default="", description="文件功能描述")


class ModuleOutput(PydanticModel):
    model_config = {"extra": "ignore"}
    files: list[CodeFileOutput] = Field(default_factory=list)
    module_description: str = ""


MODULES = [
    (
        "项目配置和依赖文件",
        "生成 requirements.txt/package.json、README.md、.env.example 等配置文件",
    ),
    (
        "后端核心代码",
        "生成后端主要业务逻辑和核心 Python/JS 代码，"
        "对于 Python CLI 项目直接生成 main.py 和相关模块",
    ),
    (
        "前端代码",
        "生成前端页面和交互代码，如果是纯命令行项目则跳过（返回空 files 列表）",
    ),
]


def _check_python_syntax(content: str) -> str | None:
    """检查 Python 语法，返回错误信息或 None（无错误）"""
    try:
        ast.parse(content)
        return None
    except SyntaxError as e:
        return f"SyntaxError at line {e.lineno}: {e.msg}"


class CodingAgent(BaseAgent):
    agent_name = "coding"
    skill_categories = ["development"]

    async def execute(self, state: dict) -> dict[str, Any]:
        requirements = state["requirements"]
        architecture = state["architecture"]
        ui_ux = state["ui_ux"]
        output_dir = state["output_dir"]
        fix_context = state.get("fix_context")

        progress_events: list[dict] = []

        # ── 第一阶段：调用工具，获取代码规范 + 实际语法检查 ─────────────────────
        tools = self._get_skill_tools()
        tool_call_logs, tool_context = await self._run_with_tools(
            system_prompt=(
                "你是一名专业的代码工程师，你有一组辅助工具可以使用，"
                "请根据项目技术栈和需求自行判断是否调用工具及调用哪些工具，按需使用即可。"
            ),
            user_msg=(
                f"项目技术栈：{json.dumps(architecture.tech_stack, ensure_ascii=False)}\n"
                f"项目描述：{requirements.project_description}"
            ),
            tools=tools,
            max_rounds=3,
        )

        if tool_call_logs:
            tool_names = list({inv["tool"] for inv in tool_call_logs})
            progress_events.append({
                "type": "skills_applied",
                "stage": "coding",
                "skills": tool_names,
                "message": f"调用代码规范工具：{', '.join(tool_names)}",
                "tool_calls": tool_call_logs,
            })

        # 加载相关 Skills（文本形式，追加到提示词）
        skills_text, skill_names = await self._load_relevant_skills()
        if skill_names and not tool_call_logs:
            progress_events.append({
                "type": "skills_applied",
                "stage": "coding",
                "skills": skill_names,
                "message": f"应用技能参考：{', '.join(skill_names)}",
            })

        # ── 第二阶段：分模块生成代码 ─────────────────────────────────────────────
        if fix_context and state.get("retry_count", 0) > 0:
            all_files = await self._fix_mode(
                state, fix_context, skills_text + tool_context,
                progress_events, output_dir,
            )
        else:
            full_context = self._build_context(requirements, architecture, ui_ux)
            all_files = await self._generate_all_modules(
                full_context, skills_text + tool_context,
                progress_events, output_dir,
            )

        tech_stack = architecture.tech_stack
        deps: dict[str, list[str]] = {}
        if any(kw in str(tech_stack).lower() for kw in ["python", "fastapi", "flask"]):
            deps["python"] = []
        if any(kw in str(tech_stack).lower() for kw in ["node", "react", "vue"]):
            deps["npm"] = []

        artifact = CodingArtifact(
            files=all_files,
            dependencies=deps,
            setup_instructions=[
                f"项目已生成到 {output_dir}",
                "请查看各文件中的注释了解启动方式",
            ],
        )

        progress_events.append({
            "type": "coding_summary",
            "stage": "coding",
            "total_files": len(all_files),
            "message": f"代码生成完成，共 {len(all_files)} 个文件",
        })

        return {
            "current_stage": FactoryStage.TESTING,
            "coding": artifact,
            "fix_context": None,
            "stage_history": [FactoryStage.CODING],
            "progress_events": progress_events,
            "messages": [AIMessage(content=f"代码生成完成。共生成 {len(all_files)} 个文件。")],
        }

    # ── 正常模式：分模块生成 + 工具语法检查 + 自我反思 ──────────────────────────

    async def _generate_all_modules(
        self,
        full_context: str,
        extra_context: str,
        progress_events: list[dict],
        output_dir: str,
    ) -> list[CodeFile]:
        from software_factory.tools.json_chain import create_json_chain

        all_files: list[CodeFile] = []

        for module_name, module_desc in MODULES:
            logger.info("Generating module: %s", module_name)
            result = None
            last_error = ""

            for attempt in range(3):
                try:
                    already_paths = [f.path for f in all_files]
                    chain = create_json_chain(
                        self.llm, SYSTEM_PROMPT + extra_context, ModuleOutput
                    )
                    user_msg = (
                        f"项目上下文：\n{full_context}\n\n"
                        f"已生成的文件：{json.dumps(already_paths, ensure_ascii=False)}\n\n"
                        f"当前任务：{module_name}\n"
                        f"任务说明：{module_desc}\n\n"
                        "请生成该模块的所有必要文件。"
                    )
                    raw = await chain.ainvoke({"input": user_msg})
                    if isinstance(raw, list):
                        raw = {"files": raw}
                    if isinstance(raw, dict) and "output" in raw and isinstance(raw["output"], dict):
                        raw = raw["output"]
                    result = ModuleOutput.model_validate(raw)
                    break
                except Exception as e:
                    last_error = str(e)
                    is_retriable = (
                        "connection" in last_error.lower()
                        or "timeout" in last_error.lower()
                        or "429" in last_error
                    )
                    if is_retriable and attempt < 2:
                        import asyncio as _aio
                        await _aio.sleep(2 ** (attempt + 1))
                        continue
                    logger.warning(
                        "Module [%s] generation failed (attempt %d): %s",
                        module_name, attempt + 1, last_error[:200],
                    )
                    break

            if result is None:
                progress_events.append({
                    "type": "module_failed",
                    "stage": "coding",
                    "module": module_name,
                    "message": f"模块生成失败: {module_name} — {last_error[:100]}",
                })
                continue

            # ── 工具语法检查 + 自我反思修复 ──────────────────────────────────────
            fixed_files = await self._syntax_check_and_fix(result.files, progress_events, output_dir)

            for f in fixed_files:
                code_file = CodeFile(
                    path=f.path, content=f.content,
                    language=f.language, description=f.description,
                )
                all_files.append(code_file)
                await write_file(output_dir, f.path, f.content)
                logger.info("  Written: %s (%s)", f.path, f.language)
                progress_events.append({
                    "type": "file_created",
                    "stage": "coding",
                    "path": f.path,
                    "language": f.language,
                    "message": f"生成文件: {f.path}",
                })

            progress_events.append({
                "type": "module_complete",
                "stage": "coding",
                "module": module_name,
                "file_count": len(fixed_files),
                "message": f"模块完成: {module_name}（{len(fixed_files)} 个文件）",
            })

        return all_files

    async def _syntax_check_and_fix(
        self,
        files: list[CodeFileOutput],
        progress_events: list[dict],
        output_dir: str,
    ) -> list[CodeFileOutput]:
        """对 Python 文件调用 check_python_syntax @tool，有错误时 LLM 自我反思修复（最多 2 轮）"""
        from software_factory.tools.json_chain import create_json_chain
        from software_factory.tools.skill_tools import check_python_syntax

        result = list(files)

        for fix_round in range(2):
            error_files = []
            for f in result:
                if f.language == "python" or f.path.endswith(".py"):
                    # 使用 @tool 进行语法检查（带日志记录）
                    check_result = check_python_syntax.invoke(
                        {"code_content": f.content, "file_name": f.path}
                    )
                    logger.info("[CodingAgent] syntax check: %s", check_result)
                    if "语法错误" in check_result or "SyntaxError" in check_result:
                        error_files.append((f, check_result))

            if not error_files:
                break

            progress_events.append({
                "type": "syntax_error_found",
                "stage": "coding",
                "files": [f.path for f, _ in error_files],
                "message": (
                    f"发现语法错误，自动修复中（第 {fix_round + 1} 轮）："
                    f"{', '.join(f.path for f, _ in error_files)}"
                ),
            })

            try:
                chain = create_json_chain(self.llm, REFLECT_SYSTEM_PROMPT, ModuleOutput)
                error_details = "\n\n".join(
                    f"文件: {f.path}\n错误: {err}\n当前内容:\n```python\n{f.content}\n```"
                    for f, err in error_files
                )
                fixed_raw = await chain.ainvoke({
                    "input": f"请修复以下 Python 文件中的语法错误：\n\n{error_details}"
                })
                if isinstance(fixed_raw, list):
                    fixed_raw = {"files": fixed_raw}
                fixed_output = ModuleOutput.model_validate(fixed_raw)

                fixed_map = {f.path: f for f in fixed_output.files}
                result = [fixed_map.get(f.path, f) for f in result]

                progress_events.append({
                    "type": "syntax_fixed",
                    "stage": "coding",
                    "files": list(fixed_map.keys()),
                    "message": f"语法错误已修复：{', '.join(fixed_map.keys())}",
                })
            except Exception as e:
                logger.warning("Syntax auto-fix failed: %s", e)
                break

        return result

    # ── 修复模式：测试失败后针对性修复 ──────────────────────────────────────────

    async def _fix_mode(
        self,
        state: dict,
        fix_context: dict,
        extra_context: str,
        progress_events: list[dict],
        output_dir: str,
    ) -> list[CodeFile]:
        from software_factory.tools.json_chain import create_json_chain

        error_output = fix_context.get("error_output", "")
        failed_files = fix_context.get("failed_files", [])

        progress_events.append({
            "type": "fix_mode_start",
            "stage": "coding",
            "message": "进入自动修复模式，分析测试失败原因...",
        })
        logger.info("CodingAgent entering fix mode, error: %s", error_output[:200])

        failed_files_text = "\n\n".join(
            f"文件: {f['path']}\n```\n{f['content']}\n```"
            for f in failed_files
        )
        fix_msg = (
            f"测试执行失败，错误信息如下：\n\n```\n{error_output}\n```\n\n"
            f"相关代码文件：\n{failed_files_text}\n\n"
            "请分析错误根因，修复有问题的文件。只返回需要修改的文件，内容必须完整。"
        )

        try:
            chain = create_json_chain(self.llm, FIX_SYSTEM_PROMPT + extra_context, ModuleOutput)
            raw = await chain.ainvoke({"input": fix_msg})
            if isinstance(raw, list):
                raw = {"files": raw}
            fix_output = ModuleOutput.model_validate(raw)
        except Exception as e:
            logger.warning("Fix mode LLM call failed: %s", e)
            fix_output = ModuleOutput(files=[])

        # 工具语法检查修复后的文件
        fixed_files = await self._syntax_check_and_fix(fix_output.files, progress_events, output_dir)

        existing: dict[str, CodeFile] = {}
        if state.get("coding") and state["coding"].files:
            for f in state["coding"].files:
                existing[f.path] = f

        for f in fixed_files:
            existing[f.path] = CodeFile(
                path=f.path, content=f.content,
                language=f.language, description=f.description,
            )
            await write_file(output_dir, f.path, f.content)
            logger.info("  Fixed & Written: %s", f.path)
            progress_events.append({
                "type": "file_fixed",
                "stage": "coding",
                "path": f.path,
                "message": f"修复文件: {f.path}",
            })

        all_files = list(existing.values())
        progress_events.append({
            "type": "fix_mode_done",
            "stage": "coding",
            "fixed_count": len(fixed_files),
            "message": f"自动修复完成，修复了 {len(fixed_files)} 个文件",
        })

        return all_files

    def _build_context(self, requirements, architecture, ui_ux) -> str:
        return (
            f"项目名称：{requirements.project_name}\n"
            f"项目描述：{requirements.project_description}\n\n"
            f"功能需求：\n"
            + "\n".join(f"- {r}" for r in requirements.functional_requirements)
            + f"\n\n技术栈：{json.dumps(architecture.tech_stack, ensure_ascii=False)}\n\n"
            "API 接口：\n"
            + "\n".join(
                f"- {ep.method} {ep.path}: {ep.description}"
                for ep in architecture.api_endpoints[:10]
            )
            + f"\n\n目录结构：\n{architecture.directory_structure}\n\n"
            "页面列表：\n"
            + "\n".join(
                f"- {p.get('name', '')}: {p.get('description', '')}"
                for p in (ui_ux.pages if ui_ux else [])[:5]
            )
        )

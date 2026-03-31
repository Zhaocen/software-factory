"""
Skill 工具定义：将数据库中的 Skill 知识库转化为 LangChain @tool 可执行函数。

工具分两类：
  - 执行类：实际运行命令/检查，如语法检查、代码质量扫描、Git 操作等
  - 知识类：返回对应技能的最佳实践文本，供 LLM 参考

分类注册表 SKILL_CATEGORY_TOOLS 将 skill category 映射到工具列表，
BaseAgent._get_skill_tools() 据此为每个 Agent 组装工具集合。
"""
from __future__ import annotations

import ast
import json
import logging
import subprocess
from typing import Any

from langchain_core.tools import tool

logger = logging.getLogger(__name__)


# ── 工具调用统一日志格式 ────────────────────────────────────────────────────────
def _log_tool_call(tool_name: str, args: dict, result: str) -> None:
    preview = result[:120].replace("\n", " ")
    logger.info("[SkillTool] %-30s args=%s  =>  %s...", tool_name, str(args)[:80], preview)


# ── 从 seeds.py 读取技能内容（知识类工具复用） ───────────────────────────────────
def _seed_content(skill_name: str) -> str:
    try:
        from software_factory.db.seeds import DEFAULT_SKILLS
        for s in DEFAULT_SKILLS:
            if s["name"] == skill_name:
                return s["content"]
    except Exception:
        pass
    return f"（未找到技能：{skill_name}）"


# ╔══════════════════════════════════════════════════════════════════════════════╗
# ║  执行类工具 — category: execution                                           ║
# ╚══════════════════════════════════════════════════════════════════════════════╝

@tool
def execute_bash_command(command: str, working_dir: str = ".") -> str:
    """执行 Bash Shell 命令并返回完整输出（stdout + stderr）。
    命令最长执行 30 秒，超时自动终止。适用于简单的系统命令。"""
    args = {"command": command, "working_dir": working_dir}
    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=30,
            cwd=working_dir,
        )
        output = result.stdout + result.stderr
        out = f"退出码: {result.returncode}\n{output[:1500]}"
        _log_tool_call("execute_bash_command", args, out)
        return out
    except subprocess.TimeoutExpired:
        out = "命令执行超时（30s）"
        _log_tool_call("execute_bash_command", args, out)
        return out
    except Exception as e:
        out = f"命令执行失败: {e}"
        _log_tool_call("execute_bash_command", args, out)
        return out


# ╔══════════════════════════════════════════════════════════════════════════════╗
# ║  开发类工具 — category: development                                         ║
# ╚══════════════════════════════════════════════════════════════════════════════╝

@tool
def check_python_syntax(code_content: str, file_name: str = "code.py") -> str:
    """检查 Python 代码是否存在语法错误。
    返回 '语法正确' 或 '第 N 行语法错误: <描述>'。
    应在每个生成的 Python 文件上调用，确保代码可执行。"""
    args = {"file_name": file_name, "code_length": len(code_content)}
    try:
        ast.parse(code_content)
        out = f"{file_name}: 语法正确"
    except SyntaxError as e:
        out = f"{file_name}: 第 {e.lineno} 行语法错误 — {e.msg}"
    _log_tool_call("check_python_syntax", args, out)
    return out


@tool
def check_python_code_quality(project_dir: str) -> str:
    """使用 ruff 对指定目录进行 Python 代码静态分析（E/F/I 规则）。
    返回问题列表，若 ruff 未安装则返回提示。用于发现导入错误、未使用变量等问题。"""
    args = {"project_dir": project_dir}
    try:
        result = subprocess.run(
            ["ruff", "check", project_dir, "--select=E,F,I", "--output-format=text"],
            capture_output=True,
            text=True,
            timeout=30,
            cwd=project_dir,
        )
        output = (result.stdout + result.stderr).strip()
        out = output[:2000] if output else "未发现代码质量问题 ✓"
    except FileNotFoundError:
        out = "ruff 未安装（已跳过代码质量检查）"
    except Exception as e:
        out = f"代码质量检查失败: {e}"
    _log_tool_call("check_python_code_quality", args, out)
    return out


@tool
def get_python_cli_structure_guide() -> str:
    """获取 Python 命令行应用的标准目录结构和代码组织方式指南。
    包含单文件脚本和模块化应用两种模板，以及 main.py 编写规范。"""
    out = _seed_content("Python 命令行应用结构")
    _log_tool_call("get_python_cli_structure_guide", {}, out[:60])
    return out


# ╔══════════════════════════════════════════════════════════════════════════════╗
# ║  测试类工具 — category: testing                                             ║
# ╚══════════════════════════════════════════════════════════════════════════════╝

@tool
def run_python_unit_tests(
    project_dir: str,
    test_command: str = "python -m pytest tests/ -v --tb=short",
) -> str:
    """在本地环境（不使用 Docker）运行 Python 单元测试，返回测试结果。
    适用于快速验证测试文件语法和基础逻辑。test_command 可自定义测试命令。"""
    args = {"project_dir": project_dir, "test_command": test_command}
    try:
        result = subprocess.run(
            test_command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=60,
            cwd=project_dir,
        )
        output = result.stdout + result.stderr
        passed = result.returncode == 0
        out = (
            f"退出码: {result.returncode} — {'✓ 测试通过' if passed else '✗ 测试失败'}\n"
            f"{output[:2000]}"
        )
    except subprocess.TimeoutExpired:
        out = "测试执行超时（60s）"
    except Exception as e:
        out = f"测试执行失败: {e}"
    _log_tool_call("run_python_unit_tests", args, out)
    return out


@tool
def test_http_endpoint(
    method: str,
    url: str,
    body_json: str = "",
    expected_status: int = 200,
) -> str:
    """发起 HTTP 请求测试指定接口（需要服务已启动），返回响应状态码和内容摘要。
    method: GET/POST/PUT/DELETE。body_json: 请求体 JSON 字符串。"""
    args = {"method": method, "url": url, "expected_status": expected_status}
    try:
        import httpx  # type: ignore[import]
        body: Any = json.loads(body_json) if body_json else None
        with httpx.Client(timeout=10) as client:
            resp = getattr(client, method.lower())(url, json=body)
        passed = resp.status_code == expected_status
        out = (
            f"{'✓' if passed else '✗'} {method.upper()} {url}\n"
            f"状态码: {resp.status_code}（期望 {expected_status}）\n"
            f"响应: {resp.text[:300]}"
        )
    except ImportError:
        out = "httpx 未安装，无法进行 HTTP 接口测试（pip install httpx）"
    except Exception as e:
        out = f"HTTP 测试失败: {e}"
    _log_tool_call("test_http_endpoint", args, out)
    return out


# ╔══════════════════════════════════════════════════════════════════════════════╗
# ║  运维类工具 — category: devops                                              ║
# ╚══════════════════════════════════════════════════════════════════════════════╝

@tool
def run_git_operation(
    project_dir: str,
    operation: str,
    commit_message: str = "feat: initial generated code",
) -> str:
    """执行 Git 操作。
    operation 可选值：
    - init       初始化 Git 仓库
    - add_all    暂存所有文件（git add -A）
    - commit     提交（使用 commit_message 参数）
    - status     查看工作区状态
    - log        查看最近 5 条提交记录
    返回命令执行结果。"""
    args = {"project_dir": project_dir, "operation": operation}
    out = _run_git_operation_impl(project_dir, operation, commit_message)
    _log_tool_call("run_git_operation", args, out)
    return out


def _run_git_operation_impl(project_dir: str, operation: str, commit_message: str) -> str:
    """先尝试系统 git 命令，不可用时回退到 gitpython"""
    supported = {"init", "add_all", "commit", "status", "log"}
    if operation not in supported:
        return f"未知操作: {operation}，支持: {', '.join(supported)}"

    # 尝试系统 git
    git_bin = _find_git()
    if git_bin:
        return _git_via_subprocess(git_bin, project_dir, operation, commit_message)

    # 回退：gitpython（纯 Python，不依赖系统 git）
    logger.warning("系统 git 不可用，回退到 gitpython")
    return _git_via_gitpython(project_dir, operation, commit_message)


def _find_git() -> str:
    """返回系统 git 可执行文件路径，找不到返回空字符串"""
    import shutil
    return shutil.which("git") or ""


def _git_via_subprocess(git_bin: str, project_dir: str, operation: str, commit_message: str) -> str:
    op_cmds: dict[str, list[str]] = {
        "init": [git_bin, "init"],
        "add_all": [git_bin, "add", "-A"],
        "commit": [git_bin, "commit", "-m", commit_message],
        "status": [git_bin, "status"],
        "log": [git_bin, "log", "--oneline", "-5"],
    }
    if operation == "commit":
        subprocess.run(
            [git_bin, "config", "user.email", "ai@factory.local"],
            cwd=project_dir, capture_output=True,
        )
        subprocess.run(
            [git_bin, "config", "user.name", "AI Software Factory"],
            cwd=project_dir, capture_output=True,
        )
    try:
        result = subprocess.run(
            op_cmds[operation], capture_output=True, text=True, timeout=30, cwd=project_dir
        )
        output = result.stdout + result.stderr
        return f"git {operation}: 退出码 {result.returncode}\n{output[:500]}"
    except Exception as e:
        return f"git subprocess 失败: {e}"


def _git_via_gitpython(project_dir: str, operation: str, commit_message: str) -> str:
    try:
        import git as _git  # gitpython
        from pathlib import Path as _Path

        path = _Path(project_dir)
        if operation == "init":
            if not (path / ".git").exists():
                _git.Repo.init(path)
            return f"git init: OK ({project_dir})"

        if operation == "add_all":
            repo = _git.Repo(project_dir)
            repo.git.add(A=True)
            return "git add -A: OK"

        if operation == "commit":
            repo = _git.Repo(project_dir)
            with repo.config_writer() as cw:
                cw.set_value("user", "email", "ai@factory.local")
                cw.set_value("user", "name", "AI Software Factory")
            repo.git.add(A=True)
            if repo.is_dirty(untracked_files=True):
                c = repo.index.commit(commit_message)
                return f"git commit: OK ({c.hexsha[:8]})"
            return "git commit: nothing to commit"

        if operation == "status":
            repo = _git.Repo(project_dir)
            return f"git status: dirty={repo.is_dirty(untracked_files=True)}"

        if operation == "log":
            repo = _git.Repo(project_dir)
            commits = list(repo.iter_commits(max_count=5))
            lines = [f"{c.hexsha[:8]} {c.message.strip()}" for c in commits]
            return "git log:\n" + "\n".join(lines)

    except Exception as e:
        return f"gitpython 操作失败: {e}"
    return "未知操作"


@tool
def get_docker_template(service_type: str = "python-web") -> str:
    """获取 Docker 容器化配置模板（Dockerfile + docker-compose.yml 示例）。
    service_type 可填: python-web / node-web / generic。"""
    args = {"service_type": service_type}
    out = _seed_content("Docker 容器化部署")
    _log_tool_call("get_docker_template", args, out[:60])
    return out


# ╔══════════════════════════════════════════════════════════════════════════════╗
# ║  需求类工具 — category: requirements                                        ║
# ╚══════════════════════════════════════════════════════════════════════════════╝

@tool
def get_user_story_template() -> str:
    """获取用户故事（User Story）编写规范和模板。
    包含标准格式、验收标准示例和优先级划分方法，帮助结构化需求分析。"""
    out = """\
# 用户故事编写规范

## 标准格式
```
作为 <角色>，我想要 <功能>，以便 <价值/目的>。

验收标准：
- [ ] 条件 1：具体可验证的行为描述
- [ ] 条件 2：边界条件处理
- [ ] 条件 3：异常场景处理
```

## 优先级划分（MoSCoW）
- Must Have（必须有）：核心功能，没有则产品无法运行
- Should Have（应该有）：重要功能，影响用户体验
- Could Have（可以有）：锦上添花，有资源时再做
- Won't Have（本期不做）：明确排除，避免范围蔓延

## 功能需求 vs 非功能需求
| 类型 | 示例 |
|------|------|
| 功能需求 | 用户可以注册账号、上传文件、查看历史记录 |
| 性能需求 | 接口响应 < 200ms，支持 1000 并发 |
| 安全需求 | 密码加密存储，SQL 注入防护 |
| 可用性需求 | 错误提示友好，操作步骤 ≤ 3 步 |

## 技术约束识别关键词
- "必须用 Python/Go/Node" → 语言约束
- "需要兼容 IE" → 浏览器约束
- "不能引入付费服务" → 成本约束
- "需要离线运行" → 网络约束
"""
    _log_tool_call("get_user_story_template", {}, out[:60])
    return out


@tool
def analyze_requirement_clarity(requirement_text: str) -> str:
    """分析用户需求描述的完整性，检查是否缺少关键信息。
    返回完整性评分（0-10）和具体缺失项目列表。"""
    args = {"text_length": len(requirement_text)}
    issues = []

    # 检查关键维度
    text_lower = requirement_text.lower()
    if len(requirement_text) < 30:
        issues.append("需求描述过短（< 30 字），缺乏足够信息")
    if not any(kw in text_lower for kw in ["用户", "我", "人", "user", "we", "client"]):
        issues.append("未明确目标用户群体")
    if not any(kw in text_lower for kw in ["功能", "实现", "支持", "能够", "可以", "feature", "support"]):
        issues.append("核心功能描述不明确")
    if not any(kw in text_lower for kw in [
        "python", "java", "go", "node", "react", "vue", "django", "fastapi",
        "技术", "语言", "框架", "前端", "后端", "数据库",
    ]):
        issues.append("未提及技术偏好或约束（可选）")

    score = max(0, 10 - len(issues) * 2)
    if issues:
        out = f"需求完整性评分: {score}/10\n缺失项：\n" + "\n".join(f"- {i}" for i in issues)
    else:
        out = f"需求完整性评分: {score}/10 ✓ 需求描述完整"
    _log_tool_call("analyze_requirement_clarity", args, out)
    return out


# ╔══════════════════════════════════════════════════════════════════════════════╗
# ║  UI/UX 设计类工具 — category: ui_ux                                         ║
# ╚══════════════════════════════════════════════════════════════════════════════╝

@tool
def get_ui_design_patterns(app_type: str = "web") -> str:
    """获取常见 UI 设计模式和交互规范指南。
    app_type: web（网页应用）/ cli（命令行）/ api（API 服务，无 UI）。
    返回对应的页面结构、导航模式和组件规范。"""
    args = {"app_type": app_type}
    if app_type == "cli":
        out = """\
# CLI 应用交互设计规范

## 命令结构
```
程序名 <子命令> [选项] [参数]
示例: myapp create --name "项目" --type python
```

## 用户体验要点
- 帮助信息：`--help` / `-h` 必须支持
- 错误提示：清晰说明错误原因和修复方式
- 进度反馈：长时间操作显示进度条或 spinner
- 颜色输出：成功=绿色，警告=黄色，错误=红色（可通过 NO_COLOR 禁用）
- 退出码：0=成功，非0=失败

## 推荐库
- argparse / click / typer（命令行解析）
- rich（终端美化输出）
- tqdm（进度条）
"""
    elif app_type == "api":
        out = """\
# API 服务设计规范（无前端 UI）

## 接口文档
- 自动生成 Swagger/OpenAPI 文档（FastAPI 内置）
- 接口路径语义化，使用 HTTP 动词表达操作
- 统一错误响应格式：{detail, code, timestamp}

## 调用体验
- 支持 CORS（跨域）
- 响应压缩（gzip）
- 请求体大小限制
- 请求 ID 追踪（X-Request-ID header）
"""
    else:  # web
        out = """\
# Web 应用 UI 设计规范

## 页面布局模式
- 单页应用（SPA）：适合交互复杂的管理后台
- 多页应用（MPA）：适合内容展示型网站
- 侧边栏 + 内容区：后台管理标准布局
- 顶部导航 + 卡片：数据展示型布局

## 关键页面清单
- 首页/Dashboard：数据概览、快捷操作
- 列表页：分页/搜索/筛选/批量操作
- 详情页：完整信息展示、相关操作按钮
- 表单页：新建/编辑，含表单验证

## 组件规范
- 按钮：主操作（蓝/绿）/ 危险操作（红）/ 次要操作（灰）
- 表单：标签 + 输入框 + 校验提示三联
- 表格：固定表头、排序列、操作列
- 弹窗：确认对话框、表单弹窗（最大宽度 600px）

## 响应式断点
- 桌面：≥ 1200px（主要设计目标）
- 平板：768px - 1199px
- 移动：< 768px（按需支持）
"""
    _log_tool_call("get_ui_design_patterns", args, out[:60])
    return out


@tool
def get_color_scheme_guide(style: str = "dark") -> str:
    """获取配色方案和设计 Token 建议。
    style: dark（暗色主题）/ light（亮色主题）/ auto（跟随系统）。
    返回主色、背景色、文字色等设计变量建议。"""
    args = {"style": style}
    if style == "dark":
        out = """\
# 暗色主题配色方案

## 核心颜色变量
```css
--primary: #6366f1;      /* 主色：靛蓝紫 */
--accent:  #10b981;      /* 强调色：绿 */
--danger:  #f87171;      /* 危险/错误：红 */
--warning: #f59e0b;      /* 警告：橙黄 */

--bg-base:    #0f1117;   /* 页面背景 */
--bg-surface: #1a1b2e;   /* 卡片/面板背景 */
--bg-hover:   #252637;   /* 悬停背景 */
--border:     rgba(255,255,255,0.08);

--text-primary: #e2e8f0; /* 主文字 */
--text-muted:   #64748b; /* 次要文字 */
```

## 字体规范
- 正文：system-ui, -apple-system, sans-serif（14px/16px）
- 代码：'JetBrains Mono', 'Fira Code', monospace（13px）
- 行高：正文 1.6，代码 1.5
"""
    else:  # light or auto
        out = """\
# 亮色主题配色方案

## 核心颜色变量
```css
--primary: #4f46e5;      /* 主色：靛蓝 */
--accent:  #059669;      /* 强调色：绿 */
--danger:  #dc2626;      /* 危险/错误：红 */

--bg-base:    #f8fafc;   /* 页面背景 */
--bg-surface: #ffffff;   /* 卡片背景 */
--border:     #e2e8f0;

--text-primary: #1e293b; /* 主文字 */
--text-muted:   #94a3b8; /* 次要文字 */
```
"""
    _log_tool_call("get_color_scheme_guide", args, out[:60])
    return out


# ╔══════════════════════════════════════════════════════════════════════════════╗
# ║  架构类工具 — category: architecture                                        ║
# ╚══════════════════════════════════════════════════════════════════════════════╝

@tool
def get_database_schema_guide(orm_framework: str = "sqlalchemy") -> str:
    """获取关系型数据库 Schema 设计最佳实践指南。
    包含 SQLAlchemy 2.0 ORM 示例、索引策略和 Alembic 迁移命令。
    orm_framework: sqlalchemy / django / sequelize。"""
    args = {"orm_framework": orm_framework}
    out = _seed_content("数据库 Schema 设计")
    _log_tool_call("get_database_schema_guide", args, out[:60])
    return out


@tool
def get_restful_api_guide() -> str:
    """获取 RESTful API 设计规范指南。
    包含 URL 规则、HTTP 状态码对照表、响应格式规范和 FastAPI 代码示例。"""
    out = _seed_content("RESTful API 设计")
    _log_tool_call("get_restful_api_guide", {}, out[:60])
    return out


# ╔══════════════════════════════════════════════════════════════════════════════╗
# ║  技能分类 → 工具注册表                                                      ║
# ╚══════════════════════════════════════════════════════════════════════════════╝

SKILL_CATEGORY_TOOLS: dict[str, list] = {
    "execution": [execute_bash_command],
    "requirements": [analyze_requirement_clarity, get_user_story_template],
    "ui_ux": [get_ui_design_patterns, get_color_scheme_guide],
    "development": [check_python_syntax, check_python_code_quality, get_python_cli_structure_guide],
    "testing": [check_python_syntax, run_python_unit_tests, test_http_endpoint],
    "devops": [run_git_operation, get_docker_template],
    "architecture": [get_database_schema_guide, get_restful_api_guide],
}


def get_tools_for_categories(categories: list[str]) -> list:
    """根据 skill_categories 列表返回去重的工具集合"""
    tools: list = []
    seen: set[str] = set()
    for cat in categories:
        for t in SKILL_CATEGORY_TOOLS.get(cat, []):
            if t.name not in seen:
                tools.append(t)
                seen.add(t.name)
    return tools

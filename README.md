# FORGE AI — AI 软件工厂

> 输入一段需求描述，AI 自动完成从需求分析到部署交付的全流程软件开发。

## 功能概览

- **全流程 AI 开发**：需求分析 → 架构设计 → UI/UX → 代码生成 → 自动测试 → DevOps 配置
- **实时进度流**：通过 SSE 推送每个阶段的 LLM 输出，全程可见
- **澄清对话**：需求不明确时，AI 主动提问，用户补充后继续构建
- **多模型支持**：每个 Agent 可独立配置 LLM（Anthropic Claude、OpenAI、Ollama、DeepSeek 等）
- **Docker 沙箱测试**：在隔离容器中执行测试，资源受限、网络禁用
- **Skills 管理**：可复用的知识模板，按需注入到生成流程
- **项目空间自选**：新建项目时可指定任意本地路径存放生成代码
- **MySQL 持久化**：项目信息、Skills、运行日志均存储在 MySQL，生成文件保留在本地磁盘
- **运维日志**：每个项目的完整运行日志，在运维管理页实时查看

---

## 快速开始

### 前提条件

- Python 3.11+
- **MySQL 8.0+**（必须，用于存储项目/Skills/日志数据）
- Docker（用于沙箱测试，可选）
- 至少一个 LLM API Key

### 方式一：本地运行

**1. 准备 MySQL**

```bash
# 创建数据库（表结构由应用启动时自动创建）
mysql -u root -p -e "CREATE DATABASE software_factory CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"
```

**2. 安装依赖**

```bash
git clone <repo-url>
cd software-factory

python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate

pip install -e "."
```

**3. 配置环境变量**

```bash
cp .env.example .env
```

编辑 `.env`：

```env
# LLM API Key（至少填一个）
ANTHROPIC_API_KEY=sk-ant-...
OPENAI_COMPATIBLE_API_KEY=sk-...

# MySQL 连接（二选一）
# 方式 A：完整 URL
DB_URL=mysql+aiomysql://root:password@localhost:3306/software_factory

# 方式 B：分项填写
DB_HOST=localhost
DB_PORT=3306
DB_USER=root
DB_PASSWORD=your_password
DB_NAME=software_factory
```

**4. 启动**

```bash
source .venv/bin/activate
uvicorn software_factory.api.main:app --port 8000 --reload
# 或
bash scripts/start.sh
```

> 首次启动时会自动在数据库中创建 `projects`、`skills`、`project_logs` 三张表。

访问 [http://localhost:8000](http://localhost:8000)

---

### 方式二：Docker Compose（推荐，含 MySQL）

```bash
cp .env.example .env
# 编辑 .env，填写 LLM API Key 和 DB 密码

docker-compose up -d
```

Docker Compose 会自动启动：
- `sf-mysql`：MySQL 8.0 服务（数据持久化到 `mysql_data` volume）
- `sf-app`：FastAPI 应用（等待 MySQL 健康后启动）

**自定义密码（推荐）：**

在 `.env` 中设置：

```env
DB_USER=forge
DB_PASSWORD=your_strong_password
DB_NAME=software_factory
```

查看日志：

```bash
docker-compose logs -f app
docker-compose logs -f mysql
```

停止服务：

```bash
docker-compose down          # 保留数据
docker-compose down -v       # 同时删除数据库 volume
```

---

## 使用流程

1. 打开 Web 界面，点击右上角「**新建项目**」
2. 填写需求描述，例如：
   > 我需要一个博客系统，支持文章发布、评论、用户登录，使用 Vue3 + FastAPI，需要 MySQL 数据库
3. 可选填写「**项目空间路径**」，指定生成代码的存放目录（留空则自动生成）
4. 点击「**开始构建 →**」，实时查看各阶段进度
5. 如果 AI 有疑问，会弹出澄清面板，回答后继续构建
6. 构建完成后，在「项目」页面查看生成文件和各阶段交付件

---

## 项目空间（Workspace）

每个项目都有独立的**项目空间路径**，用于存放 AI 生成的所有源代码文件。

| 场景 | 设置方式 |
|------|---------|
| 自动管理 | 留空，系统在 `./projects/proj_{id}/` 下自动创建 |
| 指定绝对路径 | 填写 `/Users/me/code/my-blog` |
| 指定相对路径 | 填写 `./workspace/blog-project` |
| 快速生成建议路径 | 点击输入框旁的「自动」按钮 |

项目信息、状态、日志存储在 **MySQL**，源代码文件存储在**本地磁盘**的 workspace 路径下，两者独立管理。

---

## 项目结构

```
software-factory/
├── src/software_factory/
│   ├── api/
│   │   ├── main.py                 # FastAPI 应用入口（启动时自动建表）
│   │   ├── sse.py                  # SSE 实时推送管理
│   │   ├── schemas.py              # 请求/响应数据结构
│   │   └── routes/
│   │       ├── factory.py          # 工厂流程路由（启动/流/澄清）
│   │       ├── projects.py         # 项目管理路由
│   │       ├── config_route.py     # 配置管理路由
│   │       └── skills.py           # Skills 管理路由
│   ├── db/
│   │   ├── database.py             # 异步 SQLAlchemy 引擎 + session 工厂
│   │   └── models.py               # ORM 模型：Project / Skill / ProjectLog
│   ├── agents/
│   │   ├── base.py                 # BaseAgent 抽象类（含重试逻辑）
│   │   ├── requirements.py         # 需求分析 Agent
│   │   ├── architecture.py         # 架构设计 Agent
│   │   ├── ui_ux.py                # UI/UX 设计 Agent
│   │   ├── coding.py               # 代码生成 Agent
│   │   ├── testing.py              # 自动测试 Agent
│   │   └── devops.py               # DevOps 配置 Agent
│   ├── orchestrator/
│   │   └── graph.py                # LangGraph StateGraph 编排
│   ├── state/
│   │   └── factory_state.py        # 全局状态 + 所有 Artifact 数据结构
│   ├── config/
│   │   └── settings.py             # Pydantic Settings 配置加载
│   └── tools/
│       ├── llm_factory.py          # LLM 实例工厂（多供应商）
│       ├── docker_executor.py      # Docker 沙箱执行器
│       ├── filesystem.py           # 异步文件操作
│       └── git_tool.py             # Git 集成
├── frontend/
│   ├── index.html                  # SPA 主页面（三页：项目/配置/运维管理）
│   ├── style.css                   # 暗色主题样式
│   └── app.js                      # Hash 路由 + 页面逻辑
├── projects/                       # 默认项目输出目录（用户可自定义）
│   └── proj_{id}/                  # 生成的源代码文件
├── config.yaml                     # Agent LLM 配置
├── docker-compose.yml              # 含 MySQL + 应用服务
├── .env.example                    # 环境变量模板
└── pyproject.toml
```

**数据库表结构：**

| 表 | 存储内容 |
|----|---------|
| `projects` | 项目元数据（名称、状态、进度、各阶段交付件摘要、workspace 路径） |
| `skills` | Skills 知识模板（名称、分类、内容、启用状态） |
| `project_logs` | 项目运行日志（阶段事件、LLM 输出片段、错误信息） |

---

## Web 界面

### 项目页（`#projects`）

展示所有项目卡片，包含状态（构建中/已完成/失败）、进度、创建时间、workspace 路径。点击项目卡片可查看：
- **构建流水线**：各阶段实时状态
- **各阶段交付件**：需求列表、技术栈、页面设计、测试结果等摘要
- **项目空间路径**：文件存储位置
- **生成文件**：可直接点击查看文件内容

### 配置页（`#config`）

通过 Tab 切换配置不同模块：

| Tab | 内容 |
|-----|------|
| 大模型配置 | 为每个 Agent 单独配置 LLM 供应商、模型、API Key、温度等 |
| Docker 环境 | 沙箱内存限制、CPU 配额、超时、网络隔离 |
| Git 配置 | 启用 Git 集成、远程仓库 URL、自动推送 |
| Skills 管理 | 创建/编辑/删除/导入可复用知识模板（数据存于 MySQL） |

### 运维管理页（`#devops`）

左侧项目列表，右侧日志查看器，查看每个项目存储在 MySQL 中的完整运行日志，包括阶段启动/完成、错误信息等。

---

## Skills 系统

Skills 是可复用的知识模板，数据存储在 MySQL `skills` 表，在生成软件时自动注入到相关 Agent 的 Prompt 中。

**支持的分类：**

| 分类 | 适用场景 |
|------|---------|
| `frontend` | React/Vue 组件规范、CSS 框架使用规范 |
| `backend` | JWT 认证、数据库设计规范、API 设计规范 |
| `testing` | 单元测试模板、测试覆盖率要求 |
| `devops` | CI/CD 流水线模板、Docker 最佳实践 |
| `general` | 通用编码规范、架构原则 |

**批量导入格式（JSON）：**

```json
[
  {
    "name": "JWT 认证规范",
    "description": "统一的 JWT 认证实现方式",
    "category": "backend",
    "content": "使用 JWT 进行无状态认证，Token 有效期 24h，刷新 Token 7天...",
    "is_active": true
  }
]
```

---

## LLM 供应商配置

`config.yaml` 中每个 Agent 支持以下供应商：

```yaml
# Anthropic Claude
requirements:
  provider: anthropic
  model: claude-sonnet-4-6
  api_key: sk-ant-...      # 或通过 ANTHROPIC_API_KEY 环境变量

# OpenAI
coding:
  provider: openai
  model: gpt-4o
  api_key: sk-...

# OpenAI 兼容（Ollama / DeepSeek / MiniMax / vLLM 等）
architecture:
  provider: openai_compatible
  base_url: https://api.deepseek.com/v1
  model: deepseek-chat
  api_key: sk-...
  temperature: 0.2
  max_tokens: 16384
```

**Ollama 本地模型示例：**

```yaml
coding:
  provider: openai_compatible
  base_url: http://localhost:11434/v1
  model: qwen2.5-coder:32b
  api_key: ollama
  temperature: 0.1
```

---

## API 文档

启动后访问 [http://localhost:8000/docs](http://localhost:8000/docs) 查看完整 Swagger 文档。

主要接口：

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/factory/start` | 启动构建（支持 `workspace_path` 参数） |
| GET  | `/api/factory/stream/{session_id}` | SSE 实时进度流 |
| POST | `/api/factory/clarify/{session_id}` | 提交澄清回答 |
| GET  | `/api/projects/` | 列出所有项目（从 MySQL 读取） |
| GET  | `/api/projects/{id}` | 项目详情 + 文件列表 |
| DELETE | `/api/projects/{id}` | 删除项目（`?delete_files=true` 同时删除磁盘文件） |
| GET  | `/api/projects/{id}/logs` | 运行日志（从 MySQL 读取） |
| GET  | `/api/config/` | 获取配置（读 config.yaml） |
| PUT  | `/api/config/` | 更新配置（写 config.yaml） |
| GET  | `/api/skills/` | Skills 列表（从 MySQL 读取） |
| POST | `/api/skills/` | 创建 Skill |
| PUT  | `/api/skills/{id}` | 更新 Skill |
| DELETE | `/api/skills/{id}` | 删除 Skill |
| POST | `/api/skills/import` | 批量导入 |

---

## 开发

```bash
# 运行测试
pytest tests/

# 代码格式检查
ruff check src/

# 开发模式（热重载）
DEBUG=true uvicorn software_factory.api.main:app --port 8000 --reload
```

---

## 技术栈

| 层 | 技术 |
|----|------|
| AI 编排 | [LangGraph](https://github.com/langchain-ai/langgraph) 0.2+ |
| LLM 接入 | LangChain (Anthropic / OpenAI / OpenAI Compatible) |
| Web 框架 | [FastAPI](https://fastapi.tiangolo.com/) + Uvicorn |
| 实时通信 | Server-Sent Events (SSE) |
| 数据库 | MySQL 8.0 + SQLAlchemy 2.0 (async) + aiomysql |
| 配置管理 | Pydantic Settings + YAML |
| 沙箱执行 | Docker SDK |
| 版本控制 | GitPython |
| 前端 | 原生 HTML/CSS/JS（无框架，Hash 路由 SPA） |

---

## License

MIT

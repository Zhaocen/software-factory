"""预制 Skills 种子数据，应用首次启动时自动写入（若表为空）"""
from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from software_factory.db.models import Skill

DEFAULT_SKILLS: list[dict] = [
    {
        "name": "Bash 命令执行",
        "description": "在 Shell 脚本中执行系统命令，包含错误处理和输出捕获的最佳实践",
        "category": "execution",
        "content": """\
# Bash 命令执行规范

编写 Bash 脚本或执行系统命令时，遵循以下规范：

## 基本结构
```bash
#!/usr/bin/env bash
set -euo pipefail   # 遇错退出、未定义变量报错、管道失败传递

# 执行命令并捕获输出
output=$(command 2>&1)
exit_code=$?

if [[ $exit_code -ne 0 ]]; then
    echo "ERROR: command failed with exit code $exit_code" >&2
    echo "$output" >&2
    exit 1
fi
echo "$output"
```

## 关键实践
- 使用 `set -euo pipefail` 防止静默错误
- 重要命令捕获 exit code 并明确处理
- 标准错误输出到 stderr（`>&2`）
- 敏感参数用变量而非硬编码
- 长时间命令加超时：`timeout 30s command`
- 临时文件使用 `mktemp` 并在 `trap` 中清理

## 常用模式
```bash
# 检查命令是否存在
command -v docker &>/dev/null || { echo "docker not found"; exit 1; }

# 重试逻辑
for i in {1..3}; do
    command && break || { echo "Retry $i/3"; sleep 2; }
done

# 并行执行
cmd1 & cmd2 & wait
```
""",
    },
    {
        "name": "HTTP 接口测试",
        "description": "使用 pytest + httpx 编写 FastAPI/HTTP 接口的集成测试",
        "category": "testing",
        "content": """\
# HTTP 接口测试规范

使用 pytest + httpx 编写 HTTP 接口测试，适用于 FastAPI、Flask 等框架。

## 依赖
```toml
[tool.poetry.dev-dependencies]
pytest = ">=7.0"
httpx = ">=0.24"
pytest-asyncio = ">=0.21"
```

## 基本结构
```python
import pytest
import httpx

BASE_URL = "http://localhost:8000"

@pytest.fixture(scope="session")
def client():
    with httpx.Client(base_url=BASE_URL, timeout=10) as c:
        yield c

def test_get_list(client):
    res = client.get("/api/items/")
    assert res.status_code == 200
    data = res.json()
    assert isinstance(data, list)

def test_create_item(client):
    payload = {"name": "test", "value": 42}
    res = client.post("/api/items/", json=payload)
    assert res.status_code == 201
    assert res.json()["name"] == "test"

def test_not_found(client):
    res = client.get("/api/items/nonexistent-id")
    assert res.status_code == 404
```

## FastAPI TestClient（无需启动服务器）
```python
from fastapi.testclient import TestClient
from myapp.main import app

client = TestClient(app)

def test_health():
    res = client.get("/health")
    assert res.status_code == 200
```

## 关键实践
- 每个测试独立，不依赖执行顺序
- 测试覆盖：正常路径、边界条件、错误路径
- 使用 fixture 复用 client 和测试数据
- 异步接口使用 `@pytest.mark.asyncio`
""",
    },
    {
        "name": "Python 代码质量检查",
        "description": "使用 Ruff 进行代码格式化和静态分析，以及 mypy 类型检查",
        "category": "development",
        "content": """\
# Python 代码质量规范

使用 Ruff（格式化 + Lint）和 mypy（类型检查）保证代码质量。

## pyproject.toml 配置
```toml
[tool.ruff]
line-length = 100
target-version = "py311"

[tool.ruff.lint]
select = ["E", "F", "I", "UP", "B", "SIM"]
ignore = ["E501"]

[tool.ruff.format]
quote-style = "double"
indent-style = "space"

[tool.mypy]
python_version = "3.11"
strict = true
ignore_missing_imports = true
```

## 执行命令
```bash
# 格式化代码
ruff format .

# Lint 检查并自动修复
ruff check --fix .

# 类型检查
mypy src/

# 一键检查（CI 中使用）
ruff format --check . && ruff check . && mypy src/
```

## 代码规范要点
- 所有函数标注类型注解（参数 + 返回值）
- 使用 `from __future__ import annotations` 延迟求值
- 导入顺序：标准库 → 第三方 → 本地（Ruff I 规则自动整理）
- 避免裸 `except`，使用具体异常类型
- 使用 `pathlib.Path` 替代字符串路径操作
""",
    },
    {
        "name": "Docker 容器化部署",
        "description": "Dockerfile 编写规范和 Docker Compose 多服务编排最佳实践",
        "category": "devops",
        "content": """\
# Docker 容器化规范

## Dockerfile 最佳实践
```dockerfile
# 使用精简基础镜像
FROM python:3.11-slim

# 安装系统依赖（单 RUN 减少层数）
RUN apt-get update && apt-get install -y --no-install-recommends \\
    gcc curl \\
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 先复制依赖文件（利用 layer 缓存）
COPY pyproject.toml ./
RUN pip install --no-cache-dir -e ".[prod]"

# 再复制源码
COPY src/ src/
COPY config/ config/

# 非 root 用户运行
RUN useradd -m appuser && chown -R appuser /app
USER appuser

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s CMD curl -f http://localhost:8000/health || exit 1
CMD ["uvicorn", "myapp.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

## docker-compose.yml 结构
```yaml
services:
  app:
    build: .
    ports: ["8000:8000"]
    env_file: .env
    depends_on:
      db:
        condition: service_healthy
    restart: unless-stopped

  db:
    image: postgres:16-alpine
    environment:
      POSTGRES_DB: myapp
      POSTGRES_USER: myuser
      POSTGRES_PASSWORD: ${DB_PASSWORD}
    volumes:
      - db_data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U myuser"]
      interval: 10s
      timeout: 5s
      retries: 5
      start_period: 30s

volumes:
  db_data:
```

## .dockerignore
```
.venv/
__pycache__/
*.pyc
.git/
tests/
*.md
.env
```

## 常用命令
```bash
docker compose up -d --build   # 构建并启动
docker compose logs -f app     # 跟踪日志
docker compose exec app bash   # 进入容器
docker compose down -v         # 停止并删除 volume
```
""",
    },
    {
        "name": "Git 工作流",
        "description": "Git 分支管理、Commit 规范和 PR 流程",
        "category": "devops",
        "content": """\
# Git 工作流规范

## 分支策略
- `main` / `master`：生产分支，只接受 PR 合并
- `develop`：开发集成分支
- `feature/<name>`：功能分支
- `fix/<name>`：修复分支
- `release/<version>`：发布分支

## Commit Message 格式（Conventional Commits）
```
<type>(<scope>): <description>

[optional body]

[optional footer]
```

类型：`feat` | `fix` | `docs` | `style` | `refactor` | `test` | `chore`

示例：
```
feat(auth): add JWT token refresh endpoint

Implements sliding session with 7-day refresh window.
Closes #142
```

## .gitignore 关键条目
```
# Python
__pycache__/
*.pyc
.venv/
*.egg-info/
dist/

# 环境配置
.env
*.local

# IDE
.idea/
.vscode/
*.swp

# 运行时数据
logs/
*.log
```

## 常用操作
```bash
# 创建功能分支
git checkout -b feature/my-feature

# 交互式暂存（精细化 commit）
git add -p

# 修改最后一次 commit（未推送时）
git commit --amend --no-edit

# Rebase 保持线性历史
git rebase origin/main

# 标签发布
git tag -a v1.0.0 -m "Release v1.0.0"
git push origin v1.0.0
```
""",
    },
    {
        "name": "Python 单元测试",
        "description": "使用 pytest 编写结构化的单元测试，包含 fixture、mock 和覆盖率",
        "category": "testing",
        "content": """\
# Python 单元测试规范

## 依赖
```toml
[tool.poetry.dev-dependencies]
pytest = ">=7.0"
pytest-asyncio = ">=0.21"
pytest-cov = ">=4.0"
pytest-mock = ">=3.10"
```

## 目录结构
```
tests/
├── conftest.py          # 共享 fixtures
├── unit/
│   ├── test_service.py
│   └── test_utils.py
└── integration/
    └── test_api.py
```

## conftest.py 示例
```python
import pytest
from unittest.mock import AsyncMock

@pytest.fixture
def mock_db():
    return AsyncMock()

@pytest.fixture
def sample_user():
    return {"id": "user-1", "name": "Alice", "email": "alice@example.com"}
```

## 测试编写规范
```python
import pytest
from unittest.mock import patch, MagicMock

class TestUserService:
    def test_create_user_success(self, mock_db, sample_user):
        # Arrange
        service = UserService(db=mock_db)
        # Act
        result = service.create(sample_user)
        # Assert
        assert result["name"] == "Alice"
        mock_db.save.assert_called_once()

    def test_create_user_duplicate_raises(self, mock_db):
        mock_db.find.return_value = {"id": "existing"}
        service = UserService(db=mock_db)
        with pytest.raises(ValueError, match="already exists"):
            service.create({"email": "alice@example.com"})

    @pytest.mark.parametrize("email,valid", [
        ("alice@example.com", True),
        ("not-an-email", False),
        ("", False),
    ])
    def test_email_validation(self, email, valid):
        assert validate_email(email) == valid
```

## 运行命令
```bash
# 运行所有测试
pytest

# 带覆盖率报告
pytest --cov=src --cov-report=html

# 只运行标记
pytest -m "not slow"

# 详细输出
pytest -v --tb=short
```
""",
    },
    {
        "name": "数据库 Schema 设计",
        "description": "关系型数据库表结构设计规范，包含索引策略和 SQLAlchemy ORM 映射",
        "category": "architecture",
        "content": """\
# 数据库 Schema 设计规范

## 通用原则
- 每张表必须有主键（推荐 UUID 字符串或自增 BigInteger）
- 时间字段：`created_at`（DEFAULT NOW()）、`updated_at`（ON UPDATE NOW()）
- 软删除用 `deleted_at TIMESTAMP NULL` + 索引过滤
- 字符串字段设置合理上限（避免无限制 TEXT）
- 外键加索引，高频查询字段加复合索引

## SQLAlchemy 2.0 ORM 示例
```python
from datetime import datetime
from sqlalchemy import String, Text, DateTime, func, Index
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

class Base(DeclarativeBase):
    pass

class Article(Base):
    __tablename__ = "articles"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    content: Mapped[str | None] = mapped_column(Text)
    author_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), default="draft")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        Index("idx_author_status", "author_id", "status"),
        Index("idx_created", "created_at"),
    )
```

## 索引策略
- 主键自动有索引
- 外键字段（`user_id`、`project_id`）单独加索引
- 常用过滤组合建复合索引（顺序：过滤列在前，排序列在后）
- LIKE 前缀搜索可用普通索引；全文搜索用 FULLTEXT 或 Elasticsearch

## 迁移管理（Alembic）
```bash
# 初始化
alembic init migrations

# 自动生成迁移
alembic revision --autogenerate -m "add articles table"

# 执行迁移
alembic upgrade head

# 回滚一步
alembic downgrade -1
```
""",
    },
    {
        "name": "Python 命令行应用结构",
        "description": "Python CLI/脚本类项目的标准目录结构和代码组织方式",
        "category": "development",
        "content": """\
# Python 命令行应用结构规范

对于简单的 Python 命令行工具，保持结构简洁：

## 简单脚本（单文件，功能简单）
```
project/
├── main.py          # 入口，包含 main() 函数
├── requirements.txt # 依赖（若无第三方依赖可为空）
└── tests/
    └── test_main.py
```

## 模块化脚本（功能较多时拆分）
```
project/
├── main.py              # 入口：解析参数，调用核心模块
├── calculator/
│   ├── __init__.py      # 导出主要类/函数
│   └── engine.py        # 核心业务逻辑
├── requirements.txt
└── tests/
    ├── conftest.py
    └── test_engine.py
```

## main.py 模板（CLI 计算器示例）
```python
#!/usr/bin/env python3
# 简单计算器 - 支持加减乘除


def add(a: float, b: float) -> float:
    return a + b


def subtract(a: float, b: float) -> float:
    return a - b


def multiply(a: float, b: float) -> float:
    return a * b


def divide(a: float, b: float) -> float:
    if b == 0:
        raise ValueError("除数不能为零")
    return a / b


def main() -> None:
    print("=== 简单计算器 ===")
    while True:
        try:
            expr = input("请输入表达式（如 3 + 4），输入 quit 退出: ").strip()
            if expr.lower() == "quit":
                break
            parts = expr.split()
            if len(parts) != 3:
                print("格式错误，请输入: 数字 运算符 数字")
                continue
            a, op, b = float(parts[0]), parts[1], float(parts[2])
            ops = {"+": add, "-": subtract, "*": multiply, "/": divide}
            if op not in ops:
                print(f"不支持的运算符: {op}，支持: + - * /")
                continue
            result = ops[op](a, b)
            print(f"结果: {result}")
        except ValueError as e:
            print(f"错误: {e}")
        except KeyboardInterrupt:
            break


if __name__ == "__main__":
    main()
```

## 关键原则
- 纯逻辑函数放在独立模块，main.py 只做 I/O 和调用
- 每个函数只做一件事，便于单元测试
- 异常在最外层捕获，内部函数抛出具体异常
- 不引入不必要的框架（简单 CLI 不需要 FastAPI/Flask）
""",
    },
    {
        "name": "RESTful API 设计",
        "description": "RESTful API 接口设计规范，包含路径、响应格式和错误处理",
        "category": "architecture",
        "content": """\
# RESTful API 设计规范

## URL 规则
- 资源名用复数名词：`/api/users`、`/api/projects`
- 层级关系：`/api/projects/{id}/files`
- 动作用 HTTP 方法表达，避免动词 URL

| 操作 | 方法 | 路径 |
|------|------|------|
| 列表 | GET | /api/resources |
| 创建 | POST | /api/resources |
| 详情 | GET | /api/resources/{id} |
| 更新 | PUT/PATCH | /api/resources/{id} |
| 删除 | DELETE | /api/resources/{id} |

## HTTP 状态码
- 200 OK：成功读取/更新
- 201 Created：成功创建
- 204 No Content：成功删除
- 400 Bad Request：请求参数错误
- 401 Unauthorized：未认证
- 403 Forbidden：无权限
- 404 Not Found：资源不存在
- 422 Unprocessable Entity：校验失败（FastAPI 默认）
- 500 Internal Server Error：服务端异常

## 响应格式
```json
// 成功列表
{ "items": [...], "total": 100, "page": 1, "page_size": 20 }

// 成功单项
{ "id": "xxx", "name": "...", "created_at": "2024-01-01T00:00:00Z" }

// 错误
{ "detail": "Resource not found", "code": "NOT_FOUND" }
```

## FastAPI 实现示例
```python
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

router = APIRouter(prefix="/api/items", tags=["items"])

class ItemCreate(BaseModel):
    name: str
    description: str = ""

@router.get("/", response_model=list[dict])
async def list_items(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, le=100),
    db: AsyncSession = Depends(get_db),
):
    offset = (page - 1) * page_size
    result = await db.execute(
        select(Item).offset(offset).limit(page_size)
    )
    return [i.to_dict() for i in result.scalars()]

@router.post("/", response_model=dict, status_code=201)
async def create_item(body: ItemCreate, db: AsyncSession = Depends(get_db)):
    item = Item(id=str(uuid.uuid4()), **body.model_dump())
    db.add(item)
    await db.flush()
    return item.to_dict()

@router.delete("/{item_id}", status_code=204)
async def delete_item(item_id: str, db: AsyncSession = Depends(get_db)):
    item = await db.get(Item, item_id)
    if not item:
        raise HTTPException(404, "Item not found")
    await db.delete(item)
```
""",
    },
]


async def seed_default_skills(session: AsyncSession) -> int:
    """写入 DEFAULT_SKILLS 中尚不存在（按 name 判断）的预制技能，返回新增条数"""
    # 查询已有的 skill name 集合
    result = await session.execute(select(Skill.name))
    existing_names = {row[0] for row in result.fetchall()}

    added = 0
    for s in DEFAULT_SKILLS:
        if s["name"] in existing_names:
            continue
        skill = Skill(
            id=str(uuid.uuid4()),
            name=s["name"],
            description=s["description"],
            category=s["category"],
            content=s["content"],
            is_active=True,
        )
        session.add(skill)
        added += 1

    if added:
        await session.commit()
    return added

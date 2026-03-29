FROM python:3.11-slim

# 安装编译依赖（aiomysql 需要 gcc）
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 先拷贝依赖描述文件，利用 Docker 层缓存
COPY pyproject.toml .
COPY src/ src/

# 安装 Python 依赖
RUN pip install --no-cache-dir -e "."

# 拷贝运行时所需文件
COPY config.yaml .
COPY frontend/ frontend/

# 创建默认项目输出目录
RUN mkdir -p projects

EXPOSE 8000

CMD ["uvicorn", "software_factory.api.main:app", "--host", "0.0.0.0", "--port", "8000"]

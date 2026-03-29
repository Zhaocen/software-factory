# ============================================================
# AI Software Factory — 构建辅助命令
# ============================================================
#
# 用法示例：
#   make dev                          本地开发（当前平台，最常用）
#   make setup-builder                初始化多平台 builder（只需执行一次）
#   make build-amd64                  构建 x86 镜像并加载到本地 Docker
#   make build-arm64                  构建 ARM 镜像并加载到本地 Docker
#   make push REGISTRY=docker.io/you  构建 amd64+arm64 并推送到 registry
# ============================================================

IMAGE    ?= software-factory
TAG      ?= latest
BUILDER  := sf-multiplatform

# ---- 本地开发 -----------------------------------------------

.PHONY: dev
dev:
	docker compose up -d --build

.PHONY: down
down:
	docker compose down

# ---- 多平台 builder 初始化（只需执行一次）-------------------
# docker-container 驱动才支持跨平台构建

.PHONY: setup-builder
setup-builder:
	docker buildx inspect $(BUILDER) > /dev/null 2>&1 \
		|| docker buildx create --name $(BUILDER) --driver docker-container --bootstrap
	docker buildx use $(BUILDER)
	@echo "✓ Builder '$(BUILDER)' 已就绪，支持平台："
	@docker buildx inspect --bootstrap | grep Platforms

# ---- 单平台本地加载（用于测试特定平台镜像）-----------------

.PHONY: build-amd64
build-amd64: setup-builder
	docker buildx build \
		--builder $(BUILDER) \
		--platform linux/amd64 \
		-t $(IMAGE):$(TAG)-amd64 \
		--load .
	@echo "✓ 已加载镜像 $(IMAGE):$(TAG)-amd64（linux/amd64）"

.PHONY: build-arm64
build-arm64: setup-builder
	docker buildx build \
		--builder $(BUILDER) \
		--platform linux/arm64 \
		-t $(IMAGE):$(TAG)-arm64 \
		--load .
	@echo "✓ 已加载镜像 $(IMAGE):$(TAG)-arm64（linux/arm64）"

# ---- 多平台推送（需要有 registry 写权限）-------------------
# 示例：make push REGISTRY=docker.io/yourname TAG=1.0.0

.PHONY: push
push: setup-builder
ifndef REGISTRY
	$(error 请指定镜像仓库，例如：make push REGISTRY=docker.io/yourname)
endif
	docker buildx build \
		--builder $(BUILDER) \
		--platform linux/amd64,linux/arm64 \
		-t $(REGISTRY)/$(IMAGE):$(TAG) \
		-t $(REGISTRY)/$(IMAGE):latest \
		--push .
	@echo "✓ 多平台镜像已推送：$(REGISTRY)/$(IMAGE):$(TAG)"

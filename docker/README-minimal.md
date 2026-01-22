# 精简版 Docker 镜像构建说明

## 概述

精简版镜像仅包含**模型管理**和**对话功能**，移除了评估相关的依赖，可大幅减少镜像大小（约减少 400-500MB）。

## 使用方法

### 方式1：使用精简版 Dockerfile

```bash
# 构建精简版镜像
docker build -f docker/Dockerfile.minimal -t llm-eval:minimal .

# 运行容器
docker run -d \
  -p 5000:5000 \
  -e DB_ENGINE=postgresql \
  -e DB_HOST=your_db_host \
  -e DB_NAME=llm_eva \
  llm-eval:minimal
```

### 方式2：修改现有 Dockerfile

在 `docker/Dockerfile` 中，将：
```dockerfile
COPY requirements.txt .
```
改为：
```dockerfile
COPY requirements-minimal.txt requirements.txt
```

然后正常构建：
```bash
docker build -f docker/Dockerfile -t llm-eval:minimal .
```

## 已移除的功能

以下功能在精简版中不可用（需要完整版）：
- ❌ 模型评估（effectiveness evaluation）
- ❌ 性能评估（performance evaluation）
- ❌ RAG评估（RAG evaluation）
- ❌ 数据集管理（dataset management）
- ❌ 数据集下载（从 ModelScope 下载）

## 保留的功能

以下功能在精简版中可用：
- ✅ 用户认证和登录
- ✅ 模型管理（添加、编辑、删除模型）
- ✅ 对话功能（Chat）
- ✅ 仪表盘

## 依赖对比

### 完整版依赖（requirements.txt）
- 包含 evalscope、modelscope、pandas、numpy 等
- 镜像大小：约 1.5-2GB

### 精简版依赖（requirements-minimal.txt）
- 仅包含 Flask、数据库驱动、openai 等核心依赖
- 镜像大小：约 1.0-1.2GB
- **减少约 400-500MB**

## 注意事项

1. 如果后续需要使用评估功能，需要切换到完整版镜像
2. 数据库迁移不受影响，精简版和完整版使用相同的数据库结构
3. 如果只使用 MySQL，可以进一步移除 `psycopg2-binary`；如果只使用 PostgreSQL，可以移除 `PyMySQL`

# LLM-EVA Docker 环境变量配置文件
# 复制此文件为 .env 并根据实际情况修改配置

# 可选：mysql 或 postgresql
DB_ENGINE=postgresql
DB_NAME=admin1
# PostgreSQL schema（可选，留空则为 public）
DB_SCHEMA=llm_eva
DB_HOST=172.32.155.59
# MySQL 默认 3306，PostgreSQL 默认 5432
DB_PORT=31001

# MySQL 相关
# MYSQL_USER=root
# MYSQL_PASSWORD=123456
# MYSQL_CHARACTER_SET_SERVER=utf8mb4
# MYSQL_COLLATION_SERVER=utf8mb4_unicode_ci

# PostgreSQL 相关（使用时请同步将 DB_ENGINE 设为 postgresql）
POSTGRES_USER=admin1
POSTGRES_PASSWORD=Postgres123


FLASK_APP=run.py
FLASK_ENV=development
SECRET_KEY=3d6f45a5f7b8c9e1d2a0b7c8d9e0f1a2b3c4d5e6f7a8b9c0d1e2f3a4b5c6d7

SYSTEM_PROVIDER_BASE_URL=https://openrouter.ai/api/v1
SYSTEM_PROVIDER_API_KEY=ST-xxx

WTF_CSRF_ENABLED=True

WEB_PORT=5001

DATA_UPLOADS_DIR=./data/uploads
DATA_OUTPUTS_DIR=./data/outputs
DATA_LOGS_DIR=./data/logs

URL_PREFIX=/tower_talk

WORKERS=2

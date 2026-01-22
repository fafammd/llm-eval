# This file makes the 'routes' directory a Python package 
# 核心路由（必需）
from app.routes import auth_routes, dashboard_routes, models_routes, chat_routes

# 评估相关路由（可选：需要evalscope/modelscope）
try:
    from app.routes import dataset_routes
except ImportError:
    dataset_routes = None  # 精简版模式下不可用

try:
    from app.routes import evaluation_routes
except ImportError:
    evaluation_routes = None  # 精简版模式下不可用

try:
    from app.routes import perf_eval_routes
except ImportError:
    perf_eval_routes = None  # 精简版模式下不可用

try:
    from app.routes import rag_eval_routes
except ImportError:
    rag_eval_routes = None  # 精简版模式下不可用 
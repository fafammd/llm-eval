# This file makes the 'services' directory a Python package 

# 服务模块初始化文件 
# 核心服务（必需）
from app.services import model_service, chat_service, user_service

# 评估相关服务（可选：需要evalscope/modelscope）
try:
    from app.services import evaluation_service
except ImportError:
    evaluation_service = None  # 精简版模式下不可用

try:
    from app.services import perf_service
except ImportError:
    perf_service = None  # 精简版模式下不可用

try:
    from app.services import dataset_service
except ImportError:
    dataset_service = None  # 精简版模式下不可用

try:
    from app.services import rag_evaluation_service
except ImportError:
    rag_evaluation_service = None  # 精简版模式下不可用 
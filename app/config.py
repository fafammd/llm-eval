import os
from dotenv import load_dotenv

# Load environment variables from .env or .flaskenv file
load_dotenv()

def get_database_uri():
    """动态构建数据库连接URL，支持 MySQL 与 PostgreSQL"""
    engine = os.environ.get('DB_ENGINE', '').lower() or 'mysql'

    db_host = os.environ.get('DB_HOST', 'localhost')
    db_name = os.environ.get('DB_NAME', os.environ.get('MYSQL_DATABASE', 'llm_eva'))

    if engine.startswith('postgres'):
        driver = 'postgresql+psycopg2'
        db_port = os.environ.get('DB_PORT', '5432')
        db_user = os.environ.get('DB_USER', os.environ.get('POSTGRES_USER', 'postgres'))
        db_password = os.environ.get('DB_PASSWORD', os.environ.get('POSTGRES_PASSWORD', ''))
    else:
        driver = 'mysql+pymysql'
        db_port = os.environ.get('DB_PORT', '3306')
        db_user = os.environ.get('DB_USER', os.environ.get('MYSQL_USER', 'root'))
        db_password = os.environ.get('DB_PASSWORD', os.environ.get('MYSQL_PASSWORD', ''))
    
    return f"{driver}://{db_user}:{db_password}@{db_host}:{db_port}/{db_name}"

def get_uploads_dir():
    """动态获取上传目录路径，支持Docker容器环境"""
    # 检查是否在Docker容器中运行
    if os.path.exists('/app') and os.environ.get('FLASK_ENV') == 'production':
        # Docker容器环境：使用容器内的绝对路径
        return '/app/uploads'
    else:
        # 非容器环境：使用环境变量或默认路径
        env_path = os.environ.get('DATA_UPLOADS_DIR')
        if env_path:
            return env_path
        else:
            # 默认路径
            return os.path.join(os.getcwd(), 'data', 'uploads')

def get_outputs_dir():
    """动态获取输出目录路径，支持Docker容器环境"""
    # 检查是否在Docker容器中运行
    if os.path.exists('/app') and os.environ.get('FLASK_ENV') == 'production':
        # Docker容器环境：使用容器内的绝对路径
        return '/app/outputs'
    else:
        # 非容器环境：使用环境变量或默认路径
        env_path = os.environ.get('DATA_OUTPUTS_DIR')
        if env_path:
            return env_path
        else:
            # 默认路径
            return os.path.join(os.getcwd(), 'data', 'outputs')

class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'a-default-fallback-secret-key'
    # 统一路由前缀（如 /api、/tower_talk），默认为空
    URL_PREFIX = os.environ.get('URL_PREFIX', '')
    # PostgreSQL schema，留空则使用 public
    DB_SCHEMA = os.environ.get('DB_SCHEMA', '').strip()
    
    # 启用CSRF保护，保障应用安全
    WTF_CSRF_ENABLED = True
    
    # 动态构建数据库连接URL
    SQLALCHEMY_DATABASE_URI = get_database_uri()
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    SYSTEM_PROVIDER_API_KEY = os.environ.get('SYSTEM_PROVIDER_API_KEY')
    SYSTEM_PROVIDER_BASE_URL = os.environ.get('SYSTEM_PROVIDER_BASE_URL')
    
    # 文件上传配置 - 使用动态路径获取
    DATA_UPLOADS_DIR = get_uploads_dir()
    DATA_OUTPUTS_DIR = get_outputs_dir()
    
    # 文件大小限制配置
    DATASET_MAX_FILE_SIZE = int(os.environ.get('DATASET_MAX_FILE_SIZE', 50 * 1024 * 1024))  # 50MB


class DevelopmentConfig(Config):
    """开发环境配置"""
    DEBUG = True
    DEVELOPMENT = True
    
    # 开发环境下启用更详细的日志
    SQLALCHEMY_ECHO = os.environ.get('SQLALCHEMY_ECHO', 'False').lower() == 'true'
    
    # 开发环境下的模板自动重载
    TEMPLATES_AUTO_RELOAD = True
    
    # 发送文件的缓存超时时间（开发环境设为1秒，便于调试静态文件）
    SEND_FILE_MAX_AGE_DEFAULT = 1

class ProductionConfig(Config):
    """生产环境配置"""
    DEBUG = False
    DEVELOPMENT = False
    
    # 生产环境下禁用模板自动重载
    TEMPLATES_AUTO_RELOAD = False
    
    # 生产环境下的静态文件缓存时间
    SEND_FILE_MAX_AGE_DEFAULT = 604800  # 7d

# 配置映射
config = {
    'development': DevelopmentConfig,
    'production': ProductionConfig,
    'default': DevelopmentConfig
}    
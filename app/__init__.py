from flask import Flask, g, render_template, redirect, url_for, flash
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from flask_migrate import Migrate
from flask_wtf.csrf import CSRFProtect
from sqlalchemy import text
from .config import config
import datetime
import logging  # 添加logging模块导入
import os  # 添加os模块导入
# 导入数据集插件，确保@register_dataset装饰器能够正确注册
from app.adapter.custom_dataset_plugin import CustomDatasetPlugin
from logging.handlers import RotatingFileHandler

# 修复Flask-Login的redirect导入问题
import flask_login.utils
if not hasattr(flask_login.utils, 'redirect'):
    flask_login.utils.redirect = redirect
if not hasattr(flask_login.utils, 'url_for'):
    flask_login.utils.url_for = url_for

db = SQLAlchemy()
migrate = Migrate()
login_manager = LoginManager()
login_manager.login_view = 'auth.login'
login_manager.login_message = "请登录以访问此页面。"
login_manager.login_message_category = "info"

# 初始化CSRF保护
csrf = CSRFProtect()

def create_app(config_name=None):
    """创建Flask应用实例
    
    Args:
        config_name: 配置名称 ('development', 'production', 'default')
                    如果为None，则从环境变量FLASK_ENV获取
    """
    # 先根据环境变量预计算统一前缀，用于静态资源路径
    raw_prefix = os.environ.get('URL_PREFIX', '').strip()
    if raw_prefix and not raw_prefix.startswith('/'):
        raw_prefix = '/' + raw_prefix
    raw_prefix = raw_prefix.rstrip('/')
    static_url_path = (raw_prefix + '/static') if raw_prefix else '/static'

    app = Flask(__name__, static_url_path=static_url_path)
    
    # 确定配置类
    if config_name is None:
        config_name = os.environ.get('FLASK_ENV', 'development')
    
    config_class = config.get(config_name, config['default'])
    app.config.from_object(config_class)
    
    # 输出当前配置信息
    app.logger.info(f"🔧 使用配置: {config_name}")
    app.logger.info(f"🐛 调试模式: {'开启' if app.config.get('DEBUG') else '关闭'}")
    app.logger.info(f"📄 模板自动重载: {'开启' if app.config.get('TEMPLATES_AUTO_RELOAD') else '关闭'}")
    app.logger.info(f"🔒 CSRF保护: {'开启' if app.config.get('WTF_CSRF_ENABLED') else '关闭'}")
    
    # 会话配置
    app.config['SESSION_COOKIE_SECURE'] = False  # 开发环境设为False，生产环境应设为True
    app.config['SESSION_COOKIE_HTTPONLY'] = True
    app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
    app.config['PERMANENT_SESSION_LIFETIME'] = datetime.timedelta(hours=24)  # 会话24小时过期
    
    # 配置日志级别，确保INFO级别的日志能够显示
    app.logger.setLevel(logging.INFO)
    
    # 配置文件日志处理器
    # 确保日志目录存在 - 根据环境自动选择路径
    # 检查是否在容器内运行
    if os.path.exists('/app') and os.environ.get('FLASK_ENV') == 'production':
        # 容器环境：使用容器内的挂载路径
        log_dir = '/app/logs'
    else:
        # 非容器环境：使用相对路径或环境变量配置的路径
        log_dir = os.environ.get('LOG_DIR', os.path.join(os.getcwd(), 'data', 'logs'))
    
    if not os.path.exists(log_dir):
        os.makedirs(log_dir, exist_ok=True)
    
    # 配置文件日志处理器（轮转日志，每个文件最大10MB，保留5个备份）
    file_handler = RotatingFileHandler(
        os.path.join(log_dir, 'app.log'),
        maxBytes=10*1024*1024,  # 10MB
        backupCount=5,
        encoding='utf-8'
    )
    file_handler.setLevel(logging.INFO)
    
    # 配置日志格式
    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    file_handler.setFormatter(formatter)
    
    # 添加文件日志处理器
    app.logger.addHandler(file_handler)
    
    # 配置其他重要模块的日志
    # 配置数据库相关日志
    db_logger = logging.getLogger('sqlalchemy')
    db_logger.setLevel(logging.WARNING)  # 只记录警告和错误
    db_logger.addHandler(file_handler)
    
    # 配置评估服务日志
    eval_logger = logging.getLogger('app.services.evaluation_service')
    eval_logger.setLevel(logging.INFO)
    eval_logger.addHandler(file_handler)
    
    # 配置模型服务日志
    model_logger = logging.getLogger('app.services.model_service')
    model_logger.setLevel(logging.INFO)
    model_logger.addHandler(file_handler)
    
    # 配置聊天服务日志
    chat_logger = logging.getLogger('app.services.chat_service')
    chat_logger.setLevel(logging.INFO)
    chat_logger.addHandler(file_handler)
    
    # 配置根日志记录器，捕获所有未明确配置的日志
    root_logger = logging.getLogger()
    if not any(isinstance(h, RotatingFileHandler) for h in root_logger.handlers):
        root_logger.addHandler(file_handler)
        root_logger.setLevel(logging.INFO)
    
    app.logger.info(f"📝 文件日志配置完成，日志将保存到 {os.path.join(log_dir, 'app.log')}")
    
    # 如果需要更详细的控制台输出格式，可以添加以下代码
    if not app.debug:
        stream_handler = logging.StreamHandler()
        stream_handler.setLevel(logging.INFO)
        stream_handler.setFormatter(formatter)
        app.logger.addHandler(stream_handler)

    # 兼容openGauss：修复版本字符串解析问题（必须在db.init_app之前应用）
    # openGauss的版本字符串格式与PostgreSQL不同，需要特殊处理
    # 原因：SQLAlchemy的PostgreSQL方言无法解析openGauss的版本字符串格式
    # 解决：在首次连接前修补_get_server_version_info方法，自动检测并处理openGauss版本
    if os.environ.get('DB_ENGINE', '').lower() == 'postgresql':
        try:
            from sqlalchemy.dialects.postgresql import base as pg_base
            
            # 修复openGauss版本解析问题（在首次连接前应用补丁）
            try:
                # 尝试获取dialect类（兼容不同SQLAlchemy版本）
                dialect_class = None
                dialect_class_name = None
                
                # 按优先级尝试不同的类名
                for class_name in ['PG_Dialect', 'PostgreSQLDialect', 'PGDialect']:
                    if hasattr(pg_base, class_name):
                        dialect_class = getattr(pg_base, class_name)
                        dialect_class_name = class_name
                        break
                
                if dialect_class and hasattr(dialect_class, '_get_server_version_info'):
                    original_get_server_version = dialect_class._get_server_version_info
                    
                    def patched_get_server_version_info(self, connection):
                        """兼容openGauss的版本字符串解析
        
                        处理逻辑：
                        1. 先尝试使用原始方法解析（适用于标准PostgreSQL）
                        2. 如果失败（AssertionError），检查是否为openGauss
                        3. 如果是openGauss，从版本字符串中提取版本号
                        4. 如果无法提取，返回兼容版本号(9, 6)
                        """
                        try:
                            return original_get_server_version(self, connection)
                        except (AssertionError, ValueError) as e:
                            # 原始方法失败，可能是openGauss，尝试特殊处理
                            try:
                                # 使用原始连接执行SQL获取版本信息
                                raw_conn = connection.connection
                                cursor = raw_conn.cursor()
                                cursor.execute("SELECT version()")
                                version_str = cursor.fetchone()[0]
                                cursor.close()
                                
                                # 检查是否为openGauss
                                if version_str and ('openGauss' in version_str or 'opengauss' in version_str.lower()):
                                    app.logger.debug(f"检测到openGauss数据库，版本字符串: {version_str[:100]}")
                                    # 提取版本号：openGauss 6.0.1 -> (6, 0)
                                    import re
                                    match = re.search(r'openGauss\s+(\d+)\.(\d+)', version_str, re.IGNORECASE)
                                    if match:
                                        major, minor = match.groups()
                                        version_tuple = (int(major), int(minor))
                                        app.logger.info(f"✅ openGauss版本解析成功: {version_tuple}")
                                        return version_tuple
                                    # 如果无法解析，返回一个兼容的版本号
                                    app.logger.warning("无法从openGauss版本字符串中提取版本号，使用兼容版本(9, 6)")
                                    return (9, 6)
                                else:
                                    # 不是openGauss，重新抛出原始异常
                                    raise e
                            except Exception as parse_error:
                                app.logger.warning(f"解析数据库版本时出错: {parse_error}")
                                # 如果无法处理，返回兼容版本，避免应用启动失败
                                return (9, 6)
                    
                    # 应用补丁
                    dialect_class._get_server_version_info = patched_get_server_version_info
                    app.logger.info(f"✅ openGauss兼容性补丁已应用（dialect类: {dialect_class_name}）")
                else:
                    app.logger.warning("未找到PostgreSQL dialect类或_get_server_version_info方法，openGauss补丁未应用")
            except Exception as e:
                app.logger.warning(f"应用openGauss兼容性补丁时出错（将尝试继续）: {e}")
        except Exception as e:
            app.logger.warning(f"设置openGauss兼容性时出错: {e}")
    
    db.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)
    csrf.init_app(app)

    # PostgreSQL schema 支持：若设置 DB_SCHEMA，则创建并设置 search_path
    def _ensure_pg_schema():
        schema = (app.config.get('DB_SCHEMA') or '').strip()
        uri = app.config.get('SQLALCHEMY_DATABASE_URI', '')
        if not schema or not uri.startswith('postgresql'):
            return
        safe_schema = schema.replace('"', '')
        # 在应用上下文内可直接使用 db.engine
        try:
            with db.engine.begin() as conn:
                conn.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{safe_schema}"'))
                conn.execute(text(f'SET search_path TO "{safe_schema}", public'))
            app.logger.info(f"✅ PostgreSQL schema 已设置为 {safe_schema} (search_path)")
        except Exception as e:
            app.logger.warning(f"设置PostgreSQL schema时出错: {e}")

    # 需要在应用上下文内执行以获取 engine
    with app.app_context():
        # 设置连接事件监听器（用于设置search_path）
        if os.environ.get('DB_ENGINE', '').lower() == 'postgresql':
            try:
                from sqlalchemy import event
                
                @event.listens_for(db.engine, "connect", insert=True)
                def set_search_path(dbapi_conn, connection_record):
                    """在连接时设置search_path（如果配置了schema）"""
                    db_schema = app.config.get('DB_SCHEMA')
                    if db_schema and db_schema.strip():
                        try:
                            with dbapi_conn.cursor() as cursor:
                                cursor.execute(f'SET search_path TO "{db_schema.strip()}", public')
                        except Exception as e:
                            app.logger.warning(f"设置search_path时出错: {e}")
            except Exception as e:
                app.logger.warning(f"设置连接事件监听器时出错: {e}")
        
        _ensure_pg_schema()
    
    # 添加自定义Jinja2过滤器
    @app.template_filter('from_json')
    def from_json_filter(value):
        """将JSON字符串或Python字典字符串转换为Python对象，如果失败返回None"""
        import json
        import ast
        try:
            # 首先尝试标准JSON解析
            return json.loads(value)
        except (json.JSONDecodeError, TypeError, ValueError):
            try:
                # 如果JSON解析失败，尝试使用ast.literal_eval解析Python字典格式
                return ast.literal_eval(value)
            except (ValueError, SyntaxError, TypeError):
                return None

    @app.template_filter('clean_json')
    def clean_json_filter(value):
        """清理模型回答中的JSON格式，去掉代码块标记并压缩JSON"""
        import json
        import re
        
        if not value:
            return value
            
        # 去掉开头的```json或```和结尾的```
        cleaned = re.sub(r'^```(?:json)?\s*\n?', '', value.strip())
        cleaned = re.sub(r'\n?```\s*$', '', cleaned)
        
        # 尝试解析并压缩JSON
        try:
            # 尝试解析为JSON对象
            json_obj = json.loads(cleaned)
            # 返回压缩的JSON字符串（不带缩进和空格）
            return json.dumps(json_obj, ensure_ascii=False, separators=(',', ':'))
        except (json.JSONDecodeError, TypeError, ValueError):
            # 如果不是有效的JSON，返回清理后的文本
            return cleaned.strip()

    @app.before_request
    def global_vars_before_request():
        g.year = datetime.date.today().year
        
        # 处理损坏的会话数据
        from flask import session, request
        try:
            # 尝试访问会话数据，如果损坏会抛出异常
            _ = session.get('_user_id')
        except Exception as e:
            app.logger.warning(f"Session data corrupted, clearing session: {e}")
            session.clear()
            # 只对需要登录的页面进行重定向
            # 数据集列表等页面不需要登录，所以不应该强制重定向

    @app.after_request
    def after_request(response):
        # 添加缓存控制头，防止缓存问题
        if response.status_code >= 400:
            response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
            response.headers['Pragma'] = 'no-cache'
            response.headers['Expires'] = '0'
        return response

    # 统一路由前缀，可通过配置项 URL_PREFIX 设置（例如 "/api"）
    def _normalize_prefix(prefix):
        if not prefix:
            return ''
        prefix = prefix.strip()
        if not prefix:
            return ''
        if not prefix.startswith('/'):
            prefix = '/' + prefix
        return prefix.rstrip('/')

    def _merge_prefix(base_prefix, bp_prefix):
        base = _normalize_prefix(base_prefix)
        bp = _normalize_prefix(bp_prefix)
        if not base and not bp:
            return None
        if base and bp:
            return base + bp
        return base or bp

    base_prefix = app.config.get('URL_PREFIX', '')

    # 注册蓝图
    from app.routes.auth_routes import bp as auth_bp
    app.register_blueprint(auth_bp, url_prefix=_merge_prefix(base_prefix, auth_bp.url_prefix or '/auth'))

    from app.routes.dashboard_routes import bp as main_bp
    app.register_blueprint(main_bp, url_prefix=_merge_prefix(base_prefix, main_bp.url_prefix or ''))

    from app.routes.models_routes import bp as models_bp
    app.register_blueprint(models_bp, url_prefix=_merge_prefix(base_prefix, models_bp.url_prefix or ''))

    from app.routes.chat_routes import bp as chat_bp
    app.register_blueprint(chat_bp, url_prefix=_merge_prefix(base_prefix, chat_bp.url_prefix or ''))

    # 注册新的数据集蓝图
    from app.routes.dataset_routes import bp as datasets_bp
    app.register_blueprint(datasets_bp, url_prefix=_merge_prefix(base_prefix, datasets_bp.url_prefix or ''))

    from app.routes.evaluation_routes import bp as evaluations_bp
    app.register_blueprint(evaluations_bp, url_prefix=_merge_prefix(base_prefix, evaluations_bp.url_prefix or ''))

    # 注册性能评估蓝图
    from app.routes.perf_eval_routes import perf_eval_bp
    app.register_blueprint(perf_eval_bp, url_prefix=_merge_prefix(base_prefix, perf_eval_bp.url_prefix or ''))

    # 注册RAG评估蓝图
    from app.routes.rag_eval_routes import bp as rag_eval_bp
    app.register_blueprint(rag_eval_bp, url_prefix=_merge_prefix(base_prefix, rag_eval_bp.url_prefix or ''))

    # 错误处理器，需要正确缩进到create_app函数内部
    @app.errorhandler(400)
    def bad_request_error(error):
        app.logger.warning(f"400 Bad Request: {error}")
        # 检查是否是CSRF错误
        if hasattr(error, 'description') and 'CSRF' in str(error.description):
            flash("表单已过期，请重新提交。", "warning")
            return render_template('errors/csrf_error.html', 
                                 title='表单过期',
                                 error_message="表单令牌已过期，请重新提交表单。"), 400
        else:
            # 清除可能损坏的会话数据
            from flask import session
            session.clear()
            flash("请求无效，可能是会话过期导致的。", "warning")
            return render_template('errors/session_error.html', 
                                 title='会话错误',
                                 error_message="请求无效，可能是会话过期导致的。",
                                 clear_session_url=url_for('auth.clear_session')), 400

    @app.errorhandler(403)
    def forbidden_error(error):
        app.logger.warning(f"403 Forbidden: {error}")
        from flask import session
        session.clear()
        flash("您的会话已过期或无权访问此页面。", "warning")
        return render_template('errors/session_error.html', 
                             title='访问被拒绝',
                             error_message="您的会话已过期或无权访问此页面。",
                             clear_session_url=url_for('auth.clear_session')), 403

    @app.errorhandler(500)
    def internal_error(error):
        app.logger.error(f"500 Internal Server Error: {error}")
        db.session.rollback()
        flash("服务器内部错误，请稍后重试。", "error")
        return redirect(url_for('main.index'))

    # 添加CLI命令
    @app.cli.command()
    def init_db():
        """初始化数据库数据"""
        from app.models import init_database_data
        with app.app_context():
            db.create_all()
            init_database_data()
            print("数据库初始化完成")

    return app

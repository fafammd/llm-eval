from pathlib import Path
from dotenv import load_dotenv
import logging  # 添加logging模块导入
import argparse  # 添加命令行参数解析
import os
import pymysql
import psycopg2

# 先加载环境变量，再导入 create_app（否则 config 会用到尚未加载的 env）
PROJECT_ROOT = Path(__file__).resolve().parent
load_dotenv(PROJECT_ROOT / '.flaskenv')
load_dotenv(PROJECT_ROOT / '.env')

from app import create_app, db
from app.models import User, AIModel, ChatSession, ChatMessage

from pathlib import Path
from dotenv import load_dotenv
load_dotenv(dotenv_path=Path(__file__).resolve().parent / '.flaskenv')

def create_database_if_not_exists():
    """创建数据库（如果不存在），支持 MySQL / PostgreSQL"""
    engine = os.environ.get('DB_ENGINE', 'mysql').lower()
    db_host = os.environ.get('DB_HOST', 'localhost')
    db_name = os.environ.get('DB_NAME', 'llm_eva')

    if engine == 'postgresql':
        db_port = int(os.environ.get('DB_PORT', 5432))
        db_user = os.environ.get('DB_USER', os.environ.get('POSTGRES_USER', 'postgres'))
        db_password = os.environ.get('DB_PASSWORD', os.environ.get('POSTGRES_PASSWORD', ''))
        try:
            conn = psycopg2.connect(
                host=db_host,
                port=db_port,
                user=db_user,
                password=db_password,
                dbname='postgres',
                connect_timeout=10,
            )
            conn.autocommit = True
            try:
                with conn.cursor() as cur:
                    cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (db_name,))
                    if not cur.fetchone():
                        print(f"🔧 数据库 '{db_name}' 不存在，正在创建...")
                        cur.execute(f'DROP DATABASE IF EXISTS "{db_name}"')  # 确保干净创建
                        cur.execute(f'CREATE DATABASE "{db_name}"')
                        print(f"✅ 数据库 '{db_name}' 创建成功")
                    else:
                        print(f"📊 数据库 '{db_name}' 已存在")
            finally:
                conn.close()
        except Exception as e:
            print(f"⚠️ 创建数据库时出错: {e}")
            print("🔧 请确保 PostgreSQL 服务运行且用户有创建数据库权限")
            return False
    else:
        db_port = int(os.environ.get('DB_PORT', 3306))
        db_user = os.environ.get('DB_USER', os.environ.get('MYSQL_USER', 'root'))
        db_password = os.environ.get('DB_PASSWORD', os.environ.get('MYSQL_PASSWORD', ''))
        try:
            connection = pymysql.connect(
                host=db_host,
                port=db_port,
                user=db_user,
                password=db_password,
                charset='utf8mb4',
                connect_timeout=10,
            )
            try:
                with connection.cursor() as cursor:
                    cursor.execute("SELECT SCHEMA_NAME FROM INFORMATION_SCHEMA.SCHEMATA WHERE SCHEMA_NAME = %s", (db_name,))
                    result = cursor.fetchone()

                    if not result:
                        print(f"🔧 数据库 '{db_name}' 不存在，正在创建...")
                        cursor.execute(f"CREATE DATABASE `{db_name}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci")
                        connection.commit()
                        print(f"✅ 数据库 '{db_name}' 创建成功")
                    else:
                        print(f"📊 数据库 '{db_name}' 已存在")
            finally:
                connection.close()
        except Exception as e:
            print(f"⚠️ 创建数据库时出错: {e}")
            print("🔧 请确保 MySQL 服务运行且用户有创建数据库权限")
            return False

    return True

def check_and_init_database(app):
    """检查并初始化数据库"""
    try:
        # 首先确保数据库存在
        if not create_database_if_not_exists():
            return False

        with app.app_context():
            # 检查数据库是否存在表
            from sqlalchemy import text, inspect
            # 使用Flask-Migrate管理数据库迁移，而不是直接创建所有表
            from flask_migrate import upgrade as migrate_upgrade
            from flask_migrate import stamp as migrate_stamp
            from sqlalchemy import text, inspect

            print(f"应用数据库迁移... (engine={os.environ.get('DB_ENGINE')}, uri={app.config.get('SQLALCHEMY_DATABASE_URI')})")
            
            # PostgreSQL schema 处理：确保在正确的 schema 中检查和创建表
            db_schema = app.config.get('DB_SCHEMA', '').strip()
            is_postgresql = os.environ.get('DB_ENGINE', '').lower() == 'postgresql'
            
            if is_postgresql and db_schema:
                # 确保 schema 存在并设置 search_path
                try:
                    with db.engine.begin() as conn:
                        conn.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{db_schema}"'))
                        conn.execute(text(f'SET search_path TO "{db_schema}", public'))
                    print(f"✅ PostgreSQL schema '{db_schema}' 已设置")
                except Exception as schema_e:
                    print(f"⚠️ 设置 PostgreSQL schema 时出错: {schema_e}")
            
            # 检查数据库中是否有表以及是否包含rag_evaluation表
            inspector = inspect(db.engine)
            # 对于 PostgreSQL，需要指定 schema 来获取表名
            if is_postgresql and db_schema:
                # 使用 schema 参数获取指定 schema 中的表
                try:
                    tables = inspector.get_table_names(schema=db_schema)
                except Exception:
                    # 如果指定 schema 失败，尝试默认方式
                    tables = inspector.get_table_names()
            else:
                tables = inspector.get_table_names()
            
            has_tables = len(tables) > 0
            has_rag_evaluation = 'rag_evaluation' in tables
            
            # 定义关键表列表（必须存在的表）
            critical_tables = ['user', 'model', 'chat_session', 'chat_message', 'dataset', 'category']
            missing_tables = [t for t in critical_tables if t not in tables]
            
            try:
                if not has_tables:
                    # 新用户，直接升级数据库
                    print("数据库中没有表，作为新用户直接执行upgrade...")
                    migrate_upgrade()
                elif has_tables and not has_rag_evaluation:
                    # 老用户，需要先标记为before0730版本，然后再升级
                    print("检测到老用户数据库（没有rag_evaluation表），执行stamp和upgrade...")
                    migrate_stamp(revision='before0730')
                    migrate_upgrade()
                elif missing_tables:
                    # 检测到缺少关键表，尝试修复
                    print(f"⚠️ 检测到缺少关键表: {', '.join(missing_tables)}")
                    print("尝试执行数据库迁移以修复...")
                    try:
                        # 先尝试升级
                        migrate_upgrade()
                        # 再次检查
                        inspector = inspect(db.engine)
                        tables = inspector.get_table_names()
                        still_missing = [t for t in critical_tables if t not in tables]
                        if still_missing:
                            print(f"⚠️ 迁移后仍缺少表: {', '.join(still_missing)}，尝试使用db.create_all()创建...")
                            # 对于 PostgreSQL，确保在正确的 schema 中创建表
                            if is_postgresql and db_schema:
                                try:
                                    with db.engine.begin() as conn:
                                        conn.execute(text(f'SET search_path TO "{db_schema}", public'))
                                    print(f"   设置 search_path 为 '{db_schema}'")
                                except Exception as sp_e:
                                    print(f"   ⚠️ 设置 search_path 失败: {sp_e}")
                            db.create_all()
                            print("使用db.create_all()创建表完成")
                    except Exception as fix_e:
                        print(f"⚠️ 修复迁移失败: {fix_e}，尝试使用db.create_all()...")
                        import traceback
                        traceback.print_exc()
                        # 对于 PostgreSQL，确保在正确的 schema 中创建表
                        if is_postgresql and db_schema:
                            try:
                                with db.engine.begin() as conn:
                                    conn.execute(text(f'SET search_path TO "{db_schema}", public'))
                                print(f"   设置 search_path 为 '{db_schema}'")
                            except Exception as sp_e:
                                print(f"   ⚠️ 设置 search_path 失败: {sp_e}")
                        db.create_all()
                        print("使用db.create_all()创建表完成")
                    
                print("数据库迁移完成")
            except Exception as e:
                print(f"数据库迁移出现问题，尝试使用替代方法: {e}")
                import traceback
                traceback.print_exc()
                # 如果迁移出现问题，尝试使用传统的方式创建表
                # 对于 PostgreSQL，确保在正确的 schema 中创建表
                if is_postgresql and db_schema:
                    try:
                        with db.engine.begin() as conn:
                            conn.execute(text(f'SET search_path TO "{db_schema}", public'))
                        print(f"   设置 search_path 为 '{db_schema}'")
                    except Exception as sp_e:
                        print(f"   ⚠️ 设置 search_path 失败: {sp_e}")
                db.create_all()
                print("使用db.create_all()创建表完成")
            
            # 最终验证：检查关键表是否都存在
            inspector = inspect(db.engine)
            # 对于 PostgreSQL，需要指定 schema 来获取表名
            if is_postgresql and db_schema:
                try:
                    tables = inspector.get_table_names(schema=db_schema)
                except Exception:
                    tables = inspector.get_table_names()
            else:
                tables = inspector.get_table_names()
            final_missing = [t for t in critical_tables if t not in tables]
            if final_missing:
                print(f"❌ 警告：以下关键表仍然缺失: {', '.join(final_missing)}")
                print("   请手动运行 'flask db upgrade' 或检查数据库连接")
            else:
                print("✅ 所有关键表已存在")
            
            # 初始化基础数据
            print("🔄 正在初始化基础数据...")
            try:
                from app.models import init_database_data
                init_database_data()
                print("✅ 基础数据初始化完成")
            except Exception as e:
                print(f"⚠️ 基础数据初始化失败: {e}")
            
            # 同步系统模型
            print("🤖 正在同步系统模型...")
            try:
                from app.services import model_service
                model_service.sync_system_models()
                print("✅ 系统模型同步完成")
            except Exception as e:
                print(f"⚠️ 系统模型同步失败: {e}")
            
            print("🎉 数据库初始化完成！")

                
    except Exception as e:
        print(f"❌ 数据库检查失败: {e}")
        print("⚠️ 应用将继续启动，但可能需要手动初始化数据库")
        return False
    
    return True

# 创建应用实例 - 这是Flask命令行工具寻找的变量
app = create_app()

# 配置根日志级别为INFO
logging.basicConfig(level=logging.INFO)

if __name__ == '__main__':
    # 添加命令行参数支持
    parser = argparse.ArgumentParser(description='运行Flask应用')
    parser.add_argument('--port', type=int, default=5000, help='端口号 (默认: 5000)')
    parser.add_argument('--host', default='0.0.0.0', help='主机地址 (默认: 0.0.0.0)')
    parser.add_argument('--no-debug', action='store_true', help='禁用调试模式')
    parser.add_argument('--no-reload', action='store_true', help='禁用自动重载')
    parser.add_argument('--skip-db-init', action='store_true', help='跳过数据库初始化检查')
    
    args = parser.parse_args()
    
    # 数据库初始化检查（除非明确跳过）
    if not args.skip_db_init:
        print("=" * 60)
        print("🗄️ 数据库检查阶段")
        print("=" * 60)
        check_and_init_database(app)
        print()
    
    # 确定是否启用调试模式和自动重载
    debug_mode = not args.no_debug
    use_reloader = not args.no_reload
    
    print(f"🚀 启动Flask应用...")
    print(f"📍 地址: http://{args.host}:{args.port}")
    print(f"🔧 调试模式: {'开启' if debug_mode else '关闭'}")
    print(f"🔄 自动重载: {'开启' if use_reloader else '关闭'}")
    print(f"🗄️ 数据库检查: {'已跳过' if args.skip_db_init else '已完成'}")
    print(f"💡 提示: 修改代码后应用会自动重启")
    print("-" * 50)
    
    app.run(
        debug=debug_mode,
        host=args.host,
        port=args.port,
        use_reloader=use_reloader,
        use_debugger=debug_mode,
        threaded=True  # 启用多线程支持
    ) 

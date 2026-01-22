#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
数据库初始化脚本
用于Docker容器启动时初始化数据库表和基础数据
"""

import sys
import os
import time
import pymysql
import psycopg2
import psycopg2.errors

def create_database_if_not_exists():
    """创建数据库（如果不存在），支持 MySQL / PostgreSQL"""
    engine = os.environ.get('DB_ENGINE', 'mysql').lower()
    try:
        db_host = os.environ.get('DB_HOST', 'localhost')
        db_port = int(os.environ.get('DB_PORT', 3306 if engine == 'mysql' else 5432))
        db_user = os.environ.get('DB_USER', os.environ.get('MYSQL_USER', os.environ.get('POSTGRES_USER', 'root')))
        db_password = os.environ.get('DB_PASSWORD', os.environ.get('MYSQL_PASSWORD', os.environ.get('POSTGRES_PASSWORD', '')))
        db_name = os.environ.get('DB_NAME', 'llm_eva')

        if engine == 'postgresql':
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
                        cur.execute(f'CREATE DATABASE "{db_name}"')
                        print(f"✅ 数据库 '{db_name}' 创建成功")
                    else:
                        print(f"📊 数据库 '{db_name}' 已存在")
            finally:
                conn.close()
        else:
            connection = pymysql.connect(
                host=db_host,
                port=db_port,
                user=db_user,
                password=db_password,
                charset='utf8mb4',
                connect_timeout=10
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
        print("🔧 请确保数据库服务正在运行，并且用户有创建数据库的权限")
        return False
    return True

def wait_for_database():
    """等待数据库连接可用"""
    print("等待数据库连接...")
    engine = os.environ.get('DB_ENGINE', 'mysql').lower()

    db_host = os.environ.get('DB_HOST', 'localhost')
    db_port = int(os.environ.get('DB_PORT', 3306 if engine == 'mysql' else 5432))
    db_user = os.environ.get('DB_USER', os.environ.get('MYSQL_USER', os.environ.get('POSTGRES_USER', 'root')))
    db_password = os.environ.get('DB_PASSWORD', os.environ.get('MYSQL_PASSWORD', os.environ.get('POSTGRES_PASSWORD', '')))

    max_retries = 30
    retry_count = 0

    while retry_count < max_retries:
        try:
            if engine == 'postgresql':
                conn = psycopg2.connect(
                    host=db_host,
                    port=db_port,
                    user=db_user,
                    password=db_password,
                    dbname='postgres',
                    connect_timeout=5,
                )
                conn.close()
                print("PostgreSQL 服务器连接成功！")
            else:
                connection = pymysql.connect(
                    host=db_host,
                    port=db_port,
                    user=db_user,
                    password=db_password,
                    connect_timeout=5
                )
                connection.close()
                print("MySQL 服务器连接成功！")
            return True
        except Exception as e:
            retry_count += 1
            print(f"数据库服务器未就绪，等待5秒... ({retry_count}/{max_retries})")
            time.sleep(5)

    print("数据库服务器连接超时！")
    return False

def init_database():
    """初始化数据库表和数据"""
    try:
        from app import create_app, db
        from app.models import init_database_data
        
        print("初始化数据库表和数据...")
        
        app = create_app()
        with app.app_context():
            from flask_migrate import upgrade as migrate_upgrade
            from flask_migrate import stamp as migrate_stamp
            from sqlalchemy import text, inspect
            
            print("应用数据库迁移...")
            
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
                                    # 设置连接事件监听器，确保所有连接都使用正确的 search_path
                                    from sqlalchemy import event
                                    @event.listens_for(db.engine, "connect", insert=True)
                                    def set_search_path_for_create(dbapi_conn, connection_record):
                                        with dbapi_conn.cursor() as cursor:
                                            cursor.execute(f'SET search_path TO "{db_schema}", public')
                                    
                                    # 现在创建表，会自动使用正确的 search_path
                                    db.create_all()
                                    print(f"使用db.create_all()在 schema '{db_schema}' 中创建表完成")
                                except Exception as sp_e:
                                    print(f"   ⚠️ 在 schema 中创建表失败: {sp_e}")
                                    import traceback
                                    traceback.print_exc()
                                    # 回退到默认方式
                                    db.create_all()
                                    print("使用db.create_all()创建表完成（回退方式）")
                            else:
                                db.create_all()
                                print("使用db.create_all()创建表完成")
                    except Exception as fix_e:
                        print(f"⚠️ 修复迁移失败: {fix_e}，尝试使用db.create_all()...")
                        import traceback
                        traceback.print_exc()
                        # 对于 PostgreSQL，确保在正确的 schema 中创建表
                        if is_postgresql and db_schema:
                            try:
                                # 设置连接事件监听器，确保所有连接都使用正确的 search_path
                                from sqlalchemy import event
                                @event.listens_for(db.engine, "connect", insert=True)
                                def set_search_path_for_create(dbapi_conn, connection_record):
                                    with dbapi_conn.cursor() as cursor:
                                        cursor.execute(f'SET search_path TO "{db_schema}", public')
                                
                                # 现在创建表，会自动使用正确的 search_path
                                db.create_all()
                                print(f"使用db.create_all()在 schema '{db_schema}' 中创建表完成")
                            except Exception as sp_e:
                                print(f"   ⚠️ 在 schema 中创建表失败: {sp_e}")
                                import traceback
                                traceback.print_exc()
                                # 回退到默认方式
                                db.create_all()
                                print("使用db.create_all()创建表完成（回退方式）")
                        else:
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
                try:
                    # 对于 PostgreSQL，确保在正确的 schema 中创建表
                    if is_postgresql and db_schema:
                        # 设置 search_path 并创建表
                        with db.engine.begin() as conn:
                            conn.execute(text(f'SET search_path TO "{db_schema}", public'))
                            # 使用 bind 参数确保在正确的连接上创建表
                            db.create_all(bind=conn)
                        print(f"使用db.create_all()在 schema '{db_schema}' 中创建表完成")
                    else:
                        db.create_all()
                        print("使用db.create_all()创建表完成")
                except Exception as create_e:
                    print(f"❌ db.create_all()也失败: {create_e}")
                    import traceback
                    traceback.print_exc()
                    # 如果 db.create_all() 失败，尝试手动创建缺失的表
                    if is_postgresql and db_schema:
                        print("尝试手动创建缺失的表...")
                        try:
                            with db.engine.begin() as conn:
                                conn.execute(text(f'SET search_path TO "{db_schema}", public'))
                                # 手动创建 chat_message 表
                                if 'chat_message' in final_missing:
                                    conn.execute(text("""
                                        CREATE TABLE IF NOT EXISTS chat_message (
                                            id SERIAL PRIMARY KEY,
                                            session_id INTEGER NOT NULL,
                                            model_id INTEGER,
                                            role VARCHAR(20) NOT NULL,
                                            content TEXT NOT NULL,
                                            timestamp TIMESTAMP,
                                            settings_snapshot JSON,
                                            FOREIGN KEY (session_id) REFERENCES chat_session(id),
                                            FOREIGN KEY (model_id) REFERENCES model(id)
                                        )
                                    """))
                                    print("✅ 手动创建 chat_message 表成功")
                        except Exception as manual_e:
                            print(f"❌ 手动创建表也失败: {manual_e}")
                            import traceback
                            traceback.print_exc()
            
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
                print("   请手动运行 'flask db upgrade' 或检查数据库连接和权限")
                # 尝试最后一次创建缺失的表
                try:
                    print("尝试最后一次创建缺失的表...")
                    db.create_all()
                    # 再次检查
                    inspector = inspect(db.engine)
                    tables = inspector.get_table_names()
                    still_missing = [t for t in critical_tables if t not in tables]
                    if still_missing:
                        print(f"❌ 最终检查：以下表仍无法创建: {', '.join(still_missing)}")
                    else:
                        print("✅ 所有缺失的表已成功创建")
                except Exception as final_e:
                    print(f"❌ 最终创建失败: {final_e}")
            else:
                print("✅ 所有关键表已存在")

            # 初始化基础数据（只在首次部署时执行）
            print("开始初始化基础数据...")
            init_database_data()
            
            # 同步系统模型（在表创建完成后执行）
            print("同步系统模型...")
            try:
                from app.services import model_service
                model_service.sync_system_models()
                print("✅ 系统模型同步完成")
            except Exception as e:
                print(f"⚠️ 系统模型同步失败: {e}")
                # 不影响整体初始化流程
            
        print("数据库初始化完成")
        return True
        
    except Exception as e:
        print(f"数据库初始化失败: {e}")
        import traceback
        traceback.print_exc()
        return False

def main():
    """主函数"""
    print("=" * 50)
    print("开始数据库初始化")
    print("=" * 50)
    
    # 等待MySQL服务器可用
    if not wait_for_database():
        sys.exit(1)
    
    # 创建数据库（如果不存在）
    if not create_database_if_not_exists():
        sys.exit(1)
    
    # 初始化数据库
    if not init_database():
        sys.exit(1)
    
    print("数据库初始化成功完成！")
    sys.exit(0)

if __name__ == "__main__":
    main() 

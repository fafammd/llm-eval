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
            # 检查数据库中是否有表以及是否包含rag_evaluation表
            inspector = inspect(db.engine)
            tables = inspector.get_table_names()
            has_tables = len(tables) > 0
            has_rag_evaluation = 'rag_evaluation' in tables
            
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
                    
                print("数据库迁移完成")
            except Exception as e:
                print(f"数据库迁移出现问题，尝试使用替代方法: {e}")
                # 如果迁移出现问题，尝试使用传统的方式创建表
                db.create_all()
                print("使用db.create_all()创建表完成")

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

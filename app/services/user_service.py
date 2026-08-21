from app import db
from app.models import User
from flask_login import login_user, logout_user, current_user
from flask import current_app
from app.utils import get_beijing_time


def create_user(username, password):
    """Creates a new user or returns existing one if username matches."""
    user = User.query.filter_by(username=username).first()
    if user:
        return user, False  # Existing user

    new_user = User(username=username)
    new_user.set_password(password)
    db.session.add(new_user)
    try:
        db.session.commit()
        return new_user, True  # New user created
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"创建用户失败: {e}")
        return None, False


def authenticate_user(username, password, remember_me=False):
    """验证用户凭据并登录。

    流程:
    1. 检查用户是否存在
    2. 检查账户是否被锁定
    3. 验证密码
       - 成功: 重置失败计数，调用 login_user
       - 失败: 递增失败计数，达到阈值触发锁定

    Returns:
        tuple: (user, error_message) - 成功时 user 为用户对象，失败时 error_message 为错误提示
    """
    user = User.query.filter_by(username=username).first()
    if not user:
        return None, '用户名或密码无效。'

    # 检查锁定状态
    if user.is_locked():
        remaining = user.get_lock_remaining_seconds()
        minutes = remaining // 60
        seconds = remaining % 60
        return None, f'账户已被锁定，请 {minutes}分{seconds}秒 后重试，或联系管理员解锁。'

    # 验证密码
    if user.check_password(password):
        user.reset_failed_attempts()
        login_user(user, remember=remember_me)
        return user, None
    else:
        # 密码错误，递增失败计数
        max_attempts = current_app.config.get('MAX_LOGIN_ATTEMPTS', 3)
        base_minutes = current_app.config.get('BASE_LOCKOUT_MINUTES', 10)
        user.increment_failed_attempt(
            max_attempts=max_attempts,
            base_lockout_minutes=base_minutes,
        )

        remaining_attempts = max_attempts - user.failed_login_attempts
        if remaining_attempts <= 0:
            # 刚被锁定
            remaining = user.get_lock_remaining_seconds()
            minutes = remaining // 60
            seconds = remaining % 60
            return None, f'密码错误次数过多，账户已被锁定 {minutes}分{seconds}秒。请联系管理员解锁或等待自动解锁。'
        else:
            return None, f'用户名或密码无效。还剩 {remaining_attempts} 次尝试机会。'


def admin_unlock_user(user_id):
    """管理员解锁用户账户

    Args:
        user_id: 要解锁的用户ID

    Returns:
        tuple: (success, message)
    """
    user = User.query.get(user_id)
    if not user:
        return False, '用户不存在。'
    user.admin_unlock()
    return True, f'用户 {user.username} 已解锁。'


def get_locked_users():
    """获取所有被锁定的用户列表"""
    now = get_beijing_time()
    return User.query.filter(User.locked_until != None, User.locked_until > now).all()


def change_user_password(user, current_password, new_password):
    """Changes the password for a user."""
    if user.check_password(current_password):
        user.set_password(new_password)
        db.session.add(user)
        try:
            db.session.commit()
            return True
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"修改密码失败: {e}")
            return False
    return False


def logout_current_user():
    """Logs out the current user."""
    logout_user()

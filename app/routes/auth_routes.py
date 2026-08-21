from flask import Blueprint, render_template, redirect, url_for, flash, request, session, Response, jsonify
from flask_login import login_user, logout_user, login_required, current_user
from app.forms import LoginForm, ChangePasswordForm
from app.models import User
from app import db
from app.services import user_service
from app.services import captcha_service

bp = Blueprint('auth', __name__)


@bp.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('main.dashboard'))

    form = LoginForm()
    if form.validate_on_submit():
        # 1. 验证图片验证码
        is_valid, captcha_error = captcha_service.verify_captcha(form.captcha.data)
        if not is_valid:
            flash(captcha_error, 'danger')
            return render_template('auth/login.html', title='登录', form=form)

        # 2. 新用户自动创建
        user = User.query.filter_by(username=form.username.data).first()
        if user is None:
            user, created = user_service.create_user(form.username.data, form.username.data)
            if created:
                flash('新用户已创建，初始密码与用户名相同。请及时修改密码。', 'info')
                user_service.authenticate_user(form.username.data, form.username.data, form.remember_me.data)
                return redirect(url_for('main.dashboard'))
            elif user is None:
                flash('创建用户时发生错误，请重试。', 'danger')
                return render_template('auth/login.html', title='登录', form=form)

        # 3. 验证凭据（含锁定检查）
        authenticated_user, error_msg = user_service.authenticate_user(
            form.username.data, form.password.data, form.remember_me.data
        )
        if authenticated_user:
            next_page = request.args.get('next')
            # 防止开放重定向：只允许相对路径
            if not next_page or not next_page.startswith('/') or next_page.startswith('//'):
                next_page = url_for('main.dashboard')
            return redirect(next_page)
        else:
            flash(error_msg, 'danger')

    return render_template('auth/login.html', title='登录', form=form)


@bp.route('/captcha_image')
def captcha_image():
    """生成并返回验证码图片"""
    image_bytes, captcha_text = captcha_service.generate_captcha()
    captcha_service.store_captcha_in_session(captcha_text)
    return Response(image_bytes, mimetype='image/png', headers={
        'Cache-Control': 'no-cache, no-store, must-revalidate',
        'Pragma': 'no-cache',
    })


@bp.route('/check_captcha', methods=['POST'])
def check_captcha():
    """AJAX 预校验验证码（不消费，允许重试）"""
    captcha_input = request.form.get('captcha', '').strip()
    if not captcha_input:
        return jsonify({'valid': False, 'message': '请输入验证码。'})
    is_valid, error_msg = captcha_service.check_captcha(captcha_input)
    return jsonify({'valid': is_valid, 'message': error_msg or ''})


@bp.route('/logout')
@login_required
def logout():
    user_service.logout_current_user()
    return redirect(url_for('auth.login'))


@bp.route('/change_password', methods=['GET', 'POST'])
@login_required
def change_password():
    form = ChangePasswordForm()
    if form.validate_on_submit():
        if user_service.change_user_password(current_user, form.current_password.data, form.new_password.data):
            flash('密码已成功修改。', 'success')
            return redirect(url_for('main.dashboard'))
        else:
            flash('当前密码不正确或更新失败，请重试。', 'danger')
    return render_template('auth/change_password.html', title='修改密码', form=form)


@bp.route('/clear_session')
def clear_session():
    """清理会话数据的路由，用于解决会话损坏问题"""
    session.clear()
    flash('会话已清理，请重新登录。', 'info')
    return redirect(url_for('auth.login'))

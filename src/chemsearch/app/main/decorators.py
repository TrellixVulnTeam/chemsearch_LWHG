from functools import wraps

from flask import redirect, url_for, current_app, flash, abort
from flask_login import current_user


def membership_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if current_app.config['USE_AUTH']:
            if current_user.is_anonymous or not current_user.in_team:
                return redirect(url_for('main.index'))
        return f(*args, **kwargs)
    return decorated_function


def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if current_app.config['USE_AUTH']:
            if not current_user.is_admin:
                abort(403)
        return f(*args, **kwargs)
    return decorated_function

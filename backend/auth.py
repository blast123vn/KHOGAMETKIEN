from functools import wraps
from flask import session, jsonify
from werkzeug.security import generate_password_hash, check_password_hash

def hash_password(password): return generate_password_hash(password)
def verify_password(stored, password): return check_password_hash(stored, password)

def current_user(db):
    uid=session.get('user_id')
    if not uid: return None
    return db.execute('SELECT * FROM users WHERE id=? AND status=?',(uid,'active')).fetchone()

def require_login(fn):
    @wraps(fn)
    def wrapper(*a,**kw):
        if not session.get('user_id'): return jsonify(error='Bạn chưa đăng nhập.'),401
        return fn(*a,**kw)
    return wrapper

def require_roles(*roles):
    def deco(fn):
        @wraps(fn)
        def wrapper(*a,**kw):
            if not session.get('user_id'): return jsonify(error='Bạn chưa đăng nhập.'),401
            db=kw.get('db')
            if db is None:
                from .database import get_db
                db=get_db()
            user=db.execute('SELECT * FROM users WHERE id=? AND status=?',(session['user_id'],'active')).fetchone()
            if not user or user['role'] not in roles: return jsonify(error='Bạn không có quyền thực hiện thao tác này.'),403
            return fn(*a,**kw)
        return wrapper
    return deco

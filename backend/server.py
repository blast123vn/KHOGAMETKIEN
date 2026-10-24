import os, base64, hashlib, secrets
from datetime import datetime, timezone, timedelta
from pathlib import Path
from flask import Flask, request, jsonify, session, send_from_directory
from flask_cors import CORS
from werkzeug.security import generate_password_hash
from cryptography.fernet import Fernet
from dotenv import load_dotenv

BASE=Path(__file__).resolve().parent.parent
load_dotenv(BASE/'.env')

# Load environment variables before importing the database adapter.
from database import get_db, init_db
from auth import verify_password, current_user, require_login
app=Flask(__name__, static_folder=str(BASE/'frontend'), static_url_path='')
app.secret_key=os.getenv('SESSION_SECRET') or secrets.token_urlsafe(48)
app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE='Lax', SESSION_COOKIE_SECURE=os.getenv('COOKIE_SECURE','0')=='1', MAX_CONTENT_LENGTH=8*1024*1024)
CORS(app, supports_credentials=True)

raw=os.getenv('GAME_PASSWORD_KEY','')
if raw:
    try: ENC=Fernet(raw.encode())
    except Exception: raise RuntimeError('GAME_PASSWORD_KEY phải là Fernet key hợp lệ.')
else:
    ENC=Fernet(Fernet.generate_key())
    print('WARNING: GAME_PASSWORD_KEY chưa được cấu hình; mật khẩu chỉ giữ được trong phiên chạy này.')

def now(): return datetime.now(timezone.utc).isoformat()
def me_json(row):
    return {'id':row['id'],'username':row['username'],'role':row['role'],'avatar':row['avatar'] or ''}
def is_admin(u): return u and u['role']=='admin'
def is_leader(u): return u and u['role']=='leader'
def can_read_game_password(u): return u and u['role'] in ('admin','leader')
def setting(db,key):
    x=db.execute('SELECT value FROM settings WHERE key=?',(key,)).fetchone(); return x['value'] if x else None

def ensure_bootstrap():
    db=get_db(); count=db.execute('SELECT COUNT(*) c FROM users').fetchone()['c']
    if count==0:
        username=os.getenv('ADMIN_USERNAME'); password=os.getenv('ADMIN_PASSWORD')
        if not username or not password: db.close(); raise RuntimeError('Thiếu ADMIN_USERNAME/ADMIN_PASSWORD trong .env')
        db.execute('INSERT INTO users(username,password_hash,role,created_at) VALUES(?,?,?,?)',(username,generate_password_hash(password),'admin',now()))
        db.commit()
    db.close()

# Khởi tạo database khi chạy cả bằng Python lẫn Gunicorn/Render.
init_db()
ensure_bootstrap()

@app.get('/')
def index(): return send_from_directory(BASE/'frontend','index.html')
@app.get('/app.js')
def js(): return send_from_directory(BASE/'frontend','app.js')
@app.get('/style.css')
def css(): return send_from_directory(BASE/'frontend','style.css')

@app.post('/api/auth/login')
def login():
    data=request.get_json() or {}; u=(data.get('username') or '').strip(); p=data.get('password') or ''
    db=get_db(); row=db.execute('SELECT * FROM users WHERE username=? AND status=?',(u,'active')).fetchone()
    ok=row and verify_password(row['password_hash'],p)
    if not ok: db.close(); return jsonify(error='Sai tài khoản hoặc mật khẩu.'),401
    session.clear(); session['user_id']=row['id']; session.permanent=True
    db.close(); return jsonify(user=me_json(row))

@app.post('/api/auth/logout')
def logout(): session.clear(); return jsonify(ok=True)
@app.get('/api/me')
def whoami():
    db=get_db(); u=current_user(db); db.close(); return jsonify(user=me_json(u) if u else None)

@app.post('/api/auth/register')
def register():
    d=request.get_json() or {}; u=(d.get('username') or '').strip(); p=d.get('password') or ''
    if len(u)<3 or len(p)<8: return jsonify(error='Tên tài khoản tối thiểu 3 ký tự, mật khẩu tối thiểu 8 ký tự.'),400
    db=get_db()
    try:
        db.execute('INSERT INTO users(username,password_hash,created_at) VALUES(?,?,?)',(u,generate_password_hash(p),now())); db.commit()
    except Exception: db.close(); return jsonify(error='Tên tài khoản đã tồn tại.'),409
    db.close(); return jsonify(ok=True)

@app.get('/api/accounts')
@require_login
def accounts():
    db=get_db(); u=current_user(db); rows=db.execute('SELECT * FROM accounts ORDER BY id DESC').fetchall()
    out=[]
    for r in rows:
        x={'id':r['id'],'game':r['game'],'code':r['code'],'name':r['name'],'note':r['note'] or ''}
        if is_admin(u): x['email']=r['email'] or ''; x['password']=ENC.decrypt(r['password_enc'].encode()).decode()
        elif is_leader(u): x['password']=ENC.decrypt(r['password_enc'].encode()).decode()
        out.append(x)
    db.close(); return jsonify(accounts=out)

@app.post('/api/accounts')
@require_login
def add_account():
    db=get_db(); u=current_user(db)
    if not is_admin(u): db.close(); return jsonify(error='Chỉ Admin được thêm tài khoản.'),403
    d=request.get_json() or {}; required=['game','code','name','password']
    if any(not str(d.get(k,'')).strip() for k in required): db.close(); return jsonify(error='Thiếu thông tin tài khoản.'),400
    if d.get('game') not in ('roblox','freefire','lienquan'):
        db.close(); return jsonify(error='Game không hợp lệ.'),400
    try:
        enc=ENC.encrypt(d['password'].encode()).decode()
        db.execute('INSERT INTO accounts(game,code,name,note,email,password_enc,created_at) VALUES(?,?,?,?,?,?,?)',(d['game'],d['code'].strip(),d['name'].strip(),d.get('note','').strip(),d.get('email','').strip(),enc,now())); db.commit()
    except Exception: db.close(); return jsonify(error='Mã tài khoản đã tồn tại hoặc dữ liệu không hợp lệ.'),409
    db.close(); return jsonify(ok=True)

@app.put('/api/accounts/<int:aid>')
@require_login
def edit_account(aid):
    db=get_db(); u=current_user(db)
    if not is_admin(u): db.close(); return jsonify(error='Chỉ Admin được chỉnh sửa.'),403
    d=request.get_json() or {}; old=db.execute('SELECT * FROM accounts WHERE id=?',(aid,)).fetchone()
    if not old: db.close(); return jsonify(error='Không tìm thấy tài khoản.'),404
    game=d.get('game',old['game'])
    if game not in ('roblox','freefire','lienquan'):
        db.close(); return jsonify(error='Game không hợp lệ.'),400
    enc=ENC.encrypt((d.get('password') or ENC.decrypt(old['password_enc'].encode()).decode()).encode()).decode()
    db.execute('UPDATE accounts SET game=?,code=?,name=?,note=?,email=?,password_enc=? WHERE id=?',(game,d.get('code',old['code']),d.get('name',old['name']),d.get('note',old['note']),d.get('email',old['email']),enc,aid)); db.commit(); db.close(); return jsonify(ok=True)

@app.delete('/api/accounts/<int:aid>')
@require_login
def delete_account(aid):
    db=get_db(); u=current_user(db)
    if not is_admin(u): db.close(); return jsonify(error='Chỉ Admin được xóa.'),403
    db.execute('DELETE FROM accounts WHERE id=?',(aid,)); db.commit(); db.close(); return jsonify(ok=True)

@app.post('/api/password-requests')
@require_login
def request_password():
    db=get_db(); u=current_user(db)
    if u['role'] in ('admin','leader'): db.close(); return jsonify(error='Tài khoản này đã có quyền xem mật khẩu.'),403
    aid=(request.get_json() or {}).get('account_id'); exists=db.execute('SELECT id FROM accounts WHERE id=?',(aid,)).fetchone()
    if not exists: db.close(); return jsonify(error='Tài khoản game không tồn tại.'),404
    db.execute('INSERT INTO password_requests(user_id,account_id,created_at) VALUES(?,?,?)',(u['id'],aid,now())); db.commit(); db.close(); return jsonify(ok=True)

@app.get('/api/password-requests')
@require_login
def requests_list():
    db=get_db(); u=current_user(db)
    if not is_admin(u): db.close(); return jsonify(error='Chỉ Admin được xem yêu cầu.'),403
    rows=db.execute('''SELECT r.id,r.status,r.created_at,u.username,a.game,a.code,a.name FROM password_requests r JOIN users u ON u.id=r.user_id JOIN accounts a ON a.id=r.account_id ORDER BY r.id DESC''').fetchall(); db.close()
    return jsonify(requests=[dict(x) for x in rows])

@app.post('/api/password-requests/<int:rid>/status')
@require_login
def request_status(rid):
    db=get_db(); u=current_user(db)
    if not is_admin(u): db.close(); return jsonify(error='Chỉ Admin được xử lý yêu cầu.'),403
    status=(request.get_json() or {}).get('status','approved')
    if status not in ('approved','rejected','pending'): db.close(); return jsonify(error='Trạng thái không hợp lệ.'),400
    db.execute('UPDATE password_requests SET status=? WHERE id=?',(status,rid)); db.commit(); db.close(); return jsonify(ok=True)

@app.get('/api/members')
@require_login
def members():
    db=get_db(); u=current_user(db)
    if not is_admin(u): db.close(); return jsonify(error='Chỉ Admin được quản lý thành viên.'),403
    rows=db.execute('SELECT id,username,role,status,avatar,created_at,last_name_change_at FROM users ORDER BY id').fetchall(); db.close(); return jsonify(members=[dict(x) for x in rows])

@app.post('/api/members/<int:uid>/role')
@require_login
def role_change(uid):
    db=get_db(); u=current_user(db)
    if not is_admin(u): db.close(); return jsonify(error='Chỉ Admin được cấp Leader.'),403
    if uid==u['id']: db.close(); return jsonify(error='Không thể đổi quyền Admin hiện tại.'),400
    role=(request.get_json() or {}).get('role','user')
    if role not in ('user','leader'): db.close(); return jsonify(error='Quyền không hợp lệ.'),400
    db.execute('UPDATE users SET role=? WHERE id=?',(role,uid)); db.commit(); db.close(); return jsonify(ok=True)

@app.post('/api/members/<int:uid>/status')
@require_login
def member_status(uid):
    db=get_db(); u=current_user(db)
    if not is_admin(u): db.close(); return jsonify(error='Chỉ Admin được khóa thành viên.'),403
    if uid==u['id']: db.close(); return jsonify(error='Không thể khóa Admin hiện tại.'),400
    status=(request.get_json() or {}).get('status','active')
    db.execute('UPDATE users SET status=? WHERE id=?', (status,uid)); db.commit(); db.close(); return jsonify(ok=True)

@app.post('/api/profile')
@require_login
def profile():
    db=get_db(); u=current_user(db); d=request.get_json() or {}; username=(d.get('username') or u['username']).strip(); nowdt=datetime.now(timezone.utc)
    if username.lower()!=u['username'].lower():
        if u['last_name_change_at']:
            last=datetime.fromisoformat(u['last_name_change_at']); remain=timedelta(days=14)-(nowdt-last)
            if remain.total_seconds()>0: db.close(); return jsonify(error=f'Bạn còn {remain.days} ngày trước khi đổi tên lại.'),429
        dup=db.execute('SELECT id FROM users WHERE lower(username)=lower(?) AND id<>?',(username,u['id'])).fetchone()
        if dup: db.close(); return jsonify(error='Tên tài khoản đã được sử dụng.'),409
        db.execute('UPDATE users SET username=?,last_name_change_at=? WHERE id=?',(username,now(),u['id']))
    if 'avatar' in d: db.execute('UPDATE users SET avatar=? WHERE id=?',(d['avatar'] or '',u['id']))
    if d.get('new_password'):
        if len(d['new_password'])<8: db.close(); return jsonify(error='Mật khẩu mới tối thiểu 8 ký tự.'),400
        db.execute('UPDATE users SET password_hash=? WHERE id=?',(generate_password_hash(d['new_password']),u['id']))
    db.commit(); fresh=db.execute('SELECT * FROM users WHERE id=?',(u['id'],)).fetchone(); db.close(); return jsonify(user=me_json(fresh))

@app.get('/api/chat')
@require_login
def chat_get():
    db=get_db(); rows=db.execute('''SELECT c.id,c.body,c.pinned,c.created_at,u.id user_id,u.username,u.role,u.avatar FROM chat_messages c JOIN users u ON u.id=c.user_id ORDER BY c.pinned DESC,c.id ASC''').fetchall(); enabled=setting(db,'chat_enabled')=='1'; db.close(); return jsonify(enabled=enabled,messages=[dict(x) for x in rows])

@app.post('/api/chat')
@require_login
def chat_post():
    db=get_db(); u=current_user(db)
    if u['role']!='admin' and setting(db,'chat_enabled')!='1': db.close(); return jsonify(error='Chat đang bị Admin tắt.'),403
    body=(request.get_json() or {}).get('body','').strip()
    if not body or len(body)>2000: db.close(); return jsonify(error='Tin nhắn không hợp lệ.'),400
    db.execute('INSERT INTO chat_messages(user_id,body,created_at) VALUES(?,?,?)',(u['id'],body,now())); db.commit(); db.close(); return jsonify(ok=True)

@app.post('/api/chat/settings')
@require_login
def chat_settings():
    db=get_db(); u=current_user(db)
    if not is_admin(u): db.close(); return jsonify(error='Chỉ Admin được đổi quyền chat.'),403
    enabled=bool((request.get_json() or {}).get('enabled')); db.execute("UPDATE settings SET value=? WHERE key='chat_enabled'",('1' if enabled else '0',)); db.commit(); db.close(); return jsonify(ok=True)

@app.post('/api/chat/<int:mid>/pin')
@require_login
def chat_pin(mid):
    db=get_db(); u=current_user(db)
    if not is_admin(u): db.close(); return jsonify(error='Chỉ Admin được ghim.'),403
    db.execute('UPDATE chat_messages SET pinned=CASE pinned WHEN 1 THEN 0 ELSE 1 END WHERE id=?',(mid,)); db.commit(); db.close(); return jsonify(ok=True)

@app.delete('/api/chat/<int:mid>')
@require_login
def chat_delete(mid):
    db=get_db(); u=current_user(db)
    if not is_admin(u): db.close(); return jsonify(error='Chỉ Admin được xóa chat.'),403
    db.execute('DELETE FROM chat_messages WHERE id=?',(mid,)); db.commit(); db.close(); return jsonify(ok=True)

@app.post('/api/admin/reveal-members')
@require_login
def reveal_members():
    db=get_db(); u=current_user(db)
    if not is_admin(u): db.close(); return jsonify(error='Chỉ Admin.'),403
    code=(request.get_json() or {}).get('code',''); expected=os.getenv('ADMIN_REVEAL_CODE','')
    if not expected or not secrets.compare_digest(code,expected): db.close(); return jsonify(error='Mã xác nhận không đúng.'),403
    rows=db.execute('SELECT id,username,role,status FROM users ORDER BY id').fetchall(); db.close(); return jsonify(members=[dict(x) for x in rows])

@app.post('/api/admin/change-password')
@require_login
def admin_password():
    db=get_db(); u=current_user(db)
    if not is_admin(u): db.close(); return jsonify(error='Chỉ Admin.'),403
    d=request.get_json() or {}; current=d.get('current_password',''); new=d.get('new_password','')
    if not verify_password(u['password_hash'],current): db.close(); return jsonify(error='Mật khẩu Admin hiện tại không đúng.'),403
    if len(new)<8: db.close(); return jsonify(error='Mật khẩu mới tối thiểu 8 ký tự.'),400
    db.execute('UPDATE users SET password_hash=? WHERE id=?',(generate_password_hash(new),u['id'])); db.commit(); db.close(); return jsonify(ok=True)

@app.errorhandler(413)
def too_large(e): return jsonify(error='Tệp hoặc dữ liệu quá lớn.'),413

if __name__=='__main__':
    init_db(); ensure_bootstrap(); app.run(host=os.getenv('HOST','127.0.0.1'),port=int(os.getenv('PORT','5000')),debug=False)

"""Хеширование готовой библиотекой и серверные сессии в SQLite."""
from hashlib import sha256
import secrets
import time

from fastapi import HTTPException, Request
from pwdlib import PasswordHash

passwords = PasswordHash.recommended()  # Argon2, реализация из pwdlib/argon2-cffi.
DUMMY_HASH = passwords.hash(secrets.token_urlsafe(32))
COOKIE_NAME = 'shelter_session'
SESSION_SECONDS = 60 * 60 * 12


def token_hash(token):
    # SHA-256 используется для случайного токена, а не для пароля.
    return sha256(token.encode('utf-8')).hexdigest()


def public_user(row):
    return {key: row[key] for key in ('id', 'name', 'login', 'role', 'created_at')}


def read_session(request: Request):
    token = request.cookies.get(COOKIE_NAME, '')
    if not token or len(token) > 128:
        return None
    with request.app.state.database.connect() as db:
        row = db.execute('''SELECT users.*,sessions.csrf_token FROM sessions
            JOIN users ON users.id=sessions.user_id
            WHERE sessions.token_hash=? AND sessions.expires_at>? AND users.role='admin' ''',
                         (token_hash(token), int(time.time()))).fetchone()
    return row


def require_admin(request: Request):
    user = read_session(request)
    if user is None:
        raise HTTPException(401, 'Войдите как администратор.')
    return user


def create_session(request, response, user):
    token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    now = int(time.time())
    with request.app.state.database.connect() as db:
        db.execute('DELETE FROM sessions WHERE expires_at<=?', (now,))
        old = request.cookies.get(COOKIE_NAME)
        if old:
            db.execute('DELETE FROM sessions WHERE token_hash=?', (token_hash(old),))
        db.execute('INSERT INTO sessions(token_hash,user_id,csrf_token,expires_at) VALUES (?,?,?,?)',
                   (token_hash(token), user['id'], csrf, now + SESSION_SECONDS))
    response.set_cookie(COOKIE_NAME, token, max_age=SESSION_SECONDS, httponly=True,
                        samesite='lax', secure=request.app.state.secure_cookies, path='/')
    return {'user': public_user(user), 'csrfToken': csrf}

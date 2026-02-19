import functools
import hashlib
import secrets
import time

from flask import request, redirect, url_for, session, abort


EXEMPT_PATHS = ("/static/", "/health", "/login", "/favicon.ico")
_login_attempts = {}
MAX_ATTEMPTS = 5
ATTEMPT_WINDOW = 60


def init_auth(app, token):
    app.secret_key = hashlib.sha256(token.encode()).hexdigest()

    @app.before_request
    def check_auth():
        for path in EXEMPT_PATHS:
            if request.path.startswith(path):
                return None

        tok = request.args.get("token")
        if tok:
            if secrets.compare_digest(tok, token):
                session["authenticated"] = True
                session.permanent = True
                return redirect(request.path)
            else:
                abort(403)

        if not session.get("authenticated"):
            return redirect(url_for("login_page"))
        return None


def check_rate_limit(ip):
    now = time.time()
    attempts = _login_attempts.get(ip, [])
    attempts = [t for t in attempts if now - t < ATTEMPT_WINDOW]
    _login_attempts[ip] = attempts
    return len(attempts) < MAX_ATTEMPTS


def record_attempt(ip):
    if ip not in _login_attempts:
        _login_attempts[ip] = []
    _login_attempts[ip].append(time.time())

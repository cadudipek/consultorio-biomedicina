import functools
import secrets

from flask import abort, flash, g, redirect, request, session, url_for

from .db import q1

PAPEIS_ORDEM = {"assistente": 1, "profissional": 2, "admin": 3}


def csrf_token():
    if "csrf" not in session:
        session["csrf"] = secrets.token_urlsafe(32)
    return session["csrf"]


def verificar_csrf():
    if request.method in ("POST", "PUT", "PATCH", "DELETE"):
        enviado = request.form.get("csrf_token") or request.headers.get("X-CSRF-Token", "")
        esperado = session.get("csrf", "")
        if not esperado or not secrets.compare_digest(enviado, esperado):
            abort(400, "Sessão expirada. Volte e tente de novo.")


def carregar_usuario():
    g.user = None
    uid = session.get("user_id")
    if uid:
        g.user = q1("SELECT * FROM usuarios WHERE id=? AND ativo=1", (uid,))
        if g.user is None:
            session.clear()


def login_required(papel_minimo="assistente"):
    def deco(f):
        @functools.wraps(f)
        def wrapper(*a, **kw):
            if g.get("user") is None:
                flash("Entre para continuar.", "info")
                return redirect(url_for("auth.login", next=request.path))
            if PAPEIS_ORDEM[g.user["papel"]] < PAPEIS_ORDEM[papel_minimo]:
                abort(403)
            return f(*a, **kw)

        return wrapper

    return deco

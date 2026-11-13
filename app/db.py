import json
import sqlite3
import unicodedata
from pathlib import Path

from flask import current_app, g, has_request_context, request, session

SCHEMA = Path(__file__).resolve().parent.parent / "schema.sql"


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(current_app.config["DATABASE"])
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


def close_db(_exc=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    db = get_db()
    db.executescript(SCHEMA.read_text(encoding="utf-8"))
    db.commit()


def q(sql, args=()):
    return get_db().execute(sql, args).fetchall()


def q1(sql, args=()):
    return get_db().execute(sql, args).fetchone()


def run(sql, args=()):
    """Executa e devolve o lastrowid. O commit é feito por quem chama (commit())."""
    return get_db().execute(sql, args).lastrowid


def commit():
    get_db().commit()


def normalizar(texto):
    texto = unicodedata.normalize("NFKD", texto or "")
    return "".join(c for c in texto if not unicodedata.combining(c)).lower().strip()


def so_digitos(texto):
    return "".join(c for c in (texto or "") if c.isdigit())


def ip_cliente():
    return request.remote_addr if has_request_context() else None


def auditar(acao, entidade, entidade_id=None, detalhes=None, usuario_id=None):
    """Registra no log append-only. Não faz commit: acompanha a transação da ação."""
    if usuario_id is None and has_request_context():
        usuario_id = session.get("user_id")
    run(
        "INSERT INTO auditoria (usuario_id, acao, entidade, entidade_id, detalhes, ip) "
        "VALUES (?,?,?,?,?,?)",
        (
            usuario_id,
            acao,
            entidade,
            entidade_id,
            json.dumps(detalhes, ensure_ascii=False, default=str) if detalhes is not None else None,
            ip_cliente(),
        ),
    )

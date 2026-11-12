import pytest
from werkzeug.security import generate_password_hash

from app import create_app
from app import db as dbmod


@pytest.fixture()
def app(tmp_path):
    app = create_app({
        "TESTING": True,
        "DATABASE": str(tmp_path / "t.db"),
        "UPLOAD_DIR": str(tmp_path / "up"),
        "BACKUP_DIR": str(tmp_path / "bk"),
        "SECRET_KEY": "teste",
    })
    import os
    os.makedirs(app.config["UPLOAD_DIR"], exist_ok=True)
    with app.app_context():
        dbmod.init_db()
        for nome, email, papel in [("Dra. Teste", "pro@demo.test", "profissional"),
                                   ("Assistente Teste", "ass@demo.test", "assistente"),
                                   ("Admin Teste", "adm@demo.test", "admin")]:
            dbmod.run("INSERT INTO usuarios (nome,email,senha_hash,papel) VALUES (?,?,?,?)",
                      (nome, email, generate_password_hash("senha-de-teste-123"), papel))
        dbmod.commit()
    return app


class Cli:
    def __init__(self, client):
        self.c = client

    def token(self):
        with self.c.session_transaction() as s:
            if "csrf" not in s:
                s["csrf"] = "tok-teste"
            return s["csrf"]

    def get(self, url, **kw):
        return self.c.get(url, **kw)

    def post(self, url, data=None, **kw):
        d = dict(data or {})
        d.setdefault("csrf_token", self.token())
        return self.c.post(url, data=d, **kw)

    def login(self, email="pro@demo.test", senha="senha-de-teste-123"):
        return self.post("/entrar", {"email": email, "senha": senha})


@pytest.fixture()
def cli(app):
    return Cli(app.test_client())


@pytest.fixture()
def pro(cli):
    r = cli.login()
    assert r.status_code == 302
    return cli


@pytest.fixture()
def ass(app):
    c = Cli(app.test_client())
    assert c.login("ass@demo.test").status_code == 302
    return c


def consulta(app, sql, args=()):
    with app.app_context():
        return [dict(r) for r in dbmod.q(sql, args)]

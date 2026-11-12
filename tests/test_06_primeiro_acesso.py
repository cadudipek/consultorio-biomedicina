from app import create_app
from app import db as dbmod


def _app(tmp_path):
    app = create_app({"TESTING": True, "PRIMEIRO_ACESSO": True, "DATABASE": str(tmp_path / "t.db"),
                      "UPLOAD_DIR": str(tmp_path / "up"), "BACKUP_DIR": str(tmp_path / "bk"), "SECRET_KEY": "x"})
    with app.app_context():
        dbmod.init_db()
    return app


def _csrf(c, url):
    c.get(url)
    with c.session_transaction() as s:
        return s["csrf"]


def test_primeiro_acesso_cria_admin_e_fecha(tmp_path):
    app = _app(tmp_path)
    c = app.test_client()
    r = c.get("/")
    assert r.status_code == 302 and "/primeiro-acesso" in r.headers["Location"]
    t = _csrf(c, "/primeiro-acesso")
    r = c.post("/primeiro-acesso", data={"csrf_token": t, "nome": "Dra. X", "email": "x@x.com",
                                         "senha": "curta", "conf": "curta"})
    assert r.status_code == 200  # senha curta recusada
    r = c.post("/primeiro-acesso", data={"csrf_token": t, "nome": "Dra. X", "email": "x@x.com",
                                         "senha": "senha-forte-123", "conf": "senha-forte-123"})
    assert r.status_code == 302
    assert c.get("/").status_code == 200  # já logada
    # depois de criado, a rota deixa de funcionar
    c2 = app.test_client()
    assert "/entrar" in c2.get("/primeiro-acesso").headers["Location"]

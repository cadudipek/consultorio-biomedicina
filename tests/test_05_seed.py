import pytest
from conftest import consulta, Cli
from app import create_app


@pytest.fixture()
def app_vazio(tmp_path):
    return create_app({"TESTING": True, "DATABASE": str(tmp_path / "s.db"), "UPLOAD_DIR": str(tmp_path / "up"),
                       "BACKUP_DIR": str(tmp_path / "bk"), "SECRET_KEY": "t"})


def test_seed_carrega_tudo(app_vazio):
    app = app_vazio
    with app.app_context():
        from tools.demo_seed import carregar
        carregar()
    assert consulta(app, "SELECT COUNT(*) n FROM pacientes")[0]["n"] == 5
    assert all("@exemplo.com" in (u["email"]) for u in consulta(app, "SELECT email FROM usuarios"))
    # integridade de tudo que foi concluído no seed
    from app.documentos import verificar_integridade
    with app.app_context():
        from app import db
        for r in db.q("SELECT id FROM atendimento_documentos WHERE hash_documento IS NOT NULL"):
            assert verificar_integridade(r["id"]) is True
    c = Cli(app.test_client())
    assert c.login("helena@exemplo.com", "demonstracao-123").status_code == 302
    for url in ["/", "/pacientes/", "/pacientes/1", "/atendimentos/1", "/atendimentos/2", "/pacientes/1/fotos",
                "/pacientes/1/comparar?antes=1&depois=2", "/modelos/", "/procedimentos/", "/exportacao/", "/configuracoes", "/pacientes/4/fotos"]:
        assert c.get(url).status_code == 200, url
    assert c.get("/atendimentos/1/pdf").data[:5] == b"%PDF-"


def test_seed_recusa_banco_com_usuarios(app):
    with app.app_context():
        from tools.demo_seed import carregar
        with pytest.raises(SystemExit):
            carregar()

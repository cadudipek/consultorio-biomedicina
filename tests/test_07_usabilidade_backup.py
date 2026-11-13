import io
import os
import tarfile

from conftest import Cli, consulta
from test_06_primeiro_acesso import _app, _csrf


def _admin(cli):
    cli.post("/sair")
    assert cli.login("adm@demo.test").status_code == 302
    return cli


def test_painel_mostra_primeiros_passos_e_modelos_prontos(pro, app):
    html = pro.get("/").get_data(as_text=True)
    assert "Primeiros passos" in html and "Começar com modelos prontos" in html
    r = pro.post("/modelos-iniciais")
    assert r.status_code == 302
    assert len(consulta(app, "SELECT id FROM termos_modelo")) == 2
    assert len(consulta(app, "SELECT id FROM procedimentos")) == 1
    # idempotente
    pro.post("/modelos-iniciais")
    assert len(consulta(app, "SELECT id FROM fichas_modelo")) == 1
    # com modelos prontos dá para abrir atendimento direto
    pro.post("/pacientes/novo", {"nome": "Paciente Fictícia"})
    r = pro.post("/atendimentos/novo", {"paciente": "1", "procedimento": "1", "data_atendimento": "2026-11-12"})
    assert r.status_code == 302
    html = pro.get("/atendimentos/1").get_data(as_text=True)
    assert "Entregar para a paciente preencher e assinar" in html


def test_assistente_nao_cria_modelos(ass):
    assert ass.post("/modelos-iniciais").status_code == 403


def _baixar_backup(cli):
    r = cli.post("/exportacao/backup", {"baixar": "1"})
    assert r.status_code == 200
    return r.data


def test_backup_e_restauracao_ida_e_volta(pro, app):
    _admin(pro)
    pro.post("/pacientes/novo", {"nome": "Antes Do Backup"})
    dados = _baixar_backup(pro)
    pro.post("/pacientes/novo", {"nome": "Depois Do Backup"})
    assert len(consulta(app, "SELECT id FROM pacientes")) == 2
    # sem confirmação não restaura
    r = pro.post("/exportacao/restaurar", {"arquivo": (io.BytesIO(dados), "b.tar.gz")}, content_type="multipart/form-data")
    assert len(consulta(app, "SELECT id FROM pacientes")) == 2
    r = pro.post("/exportacao/restaurar", {"arquivo": (io.BytesIO(dados), "b.tar.gz"), "confirmo": "1"},
                 content_type="multipart/form-data")
    assert r.status_code == 302 and "/entrar" in r.headers["Location"]
    nomes = [p["nome"] for p in consulta(app, "SELECT nome FROM pacientes")]
    assert nomes == ["Antes Do Backup"]
    # cópia de segurança do estado anterior foi guardada
    assert len(os.listdir(app.config["BACKUP_DIR"])) >= 2


def _tar(membros):
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as t:
        for nome, conteudo in membros:
            info = tarfile.TarInfo(nome)
            info.size = len(conteudo)
            t.addfile(info, io.BytesIO(conteudo))
    return buf.getvalue()


def test_restauracao_recusa_arquivos_invalidos(pro, app):
    _admin(pro)
    pro.post("/pacientes/novo", {"nome": "Fica Intacta"})
    for ruim in (b"isto nao e um tar",
                 _tar([("outra.txt", b"x")]),
                 _tar([("consultorio.db", b"lixo"), ("../fora.txt", b"x")]),
                 _tar([("consultorio.db", b"nao e sqlite")])):
        r = pro.post("/exportacao/restaurar", {"arquivo": (io.BytesIO(ruim), "b.tar.gz"), "confirmo": "1"},
                     content_type="multipart/form-data")
        assert r.status_code == 302 and "/exportacao" in r.headers["Location"]
        assert [p["nome"] for p in consulta(app, "SELECT nome FROM pacientes")] == ["Fica Intacta"]
    assert not os.path.exists(os.path.join(os.path.dirname(app.config["DATABASE"]), "fora.txt"))


def test_profissional_nao_restaura(pro):
    r = pro.post("/exportacao/restaurar", {"arquivo": (io.BytesIO(b"x"), "b.tar.gz"), "confirmo": "1"},
                 content_type="multipart/form-data")
    assert r.status_code == 403


def test_computador_novo_recupera_backup_no_primeiro_acesso(app, tmp_path):
    origem = Cli(app.test_client())
    _admin(origem)
    origem.post("/pacientes/novo", {"nome": "Paciente Do PC Antigo"})
    dados = _baixar_backup(origem)

    novo = _app(tmp_path / "novo")
    c = novo.test_client()
    t = _csrf(c, "/primeiro-acesso")
    assert "Recuperar meus dados" in c.get("/primeiro-acesso").get_data(as_text=True)
    r = c.post("/primeiro-acesso/restaurar", data={"csrf_token": t, "arquivo": (io.BytesIO(dados), "b.tar.gz")},
               content_type="multipart/form-data")
    assert r.status_code == 302 and "/entrar" in r.headers["Location"]
    cli = Cli(novo.test_client())
    assert cli.login("adm@demo.test").status_code == 302
    assert "Paciente Do PC Antigo" in cli.get("/pacientes/").get_data(as_text=True)
    # depois de existir usuário, a rota de restauração do primeiro acesso fica fechada
    r = cli.post("/primeiro-acesso/restaurar", {"arquivo": (io.BytesIO(dados), "b.tar.gz")}, content_type="multipart/form-data")
    assert r.status_code == 302 and "/entrar" in r.headers["Location"]


def test_saudacao_ignora_titulo(pro):
    assert "Olá, Teste!" in pro.get("/").get_data(as_text=True)  # usuário "Dra. Teste"

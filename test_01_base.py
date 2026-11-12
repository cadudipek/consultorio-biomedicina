from conftest import consulta


def test_acesso_exige_login(cli):
    for url in ["/", "/pacientes/", "/procedimentos/", "/configuracoes"]:
        r = cli.get(url)
        assert r.status_code == 302 and "/entrar" in r.headers["Location"]


def test_login_ok_e_senha_errada(cli, app):
    assert cli.login(senha="errada").status_code == 200
    assert cli.login().status_code == 302
    acoes = [a["acao"] for a in consulta(app, "SELECT acao FROM auditoria")]
    assert "login_falhou" in acoes and "login" in acoes


def test_bloqueio_apos_5_tentativas(cli):
    for _ in range(5):
        cli.login(senha="errada")
    r = cli.login()  # senha certa, mas bloqueado
    assert r.status_code == 200 and b"Muitas tentativas" in r.data


def test_csrf_rejeita_post_sem_token(cli):
    r = cli.c.post("/entrar", data={"email": "pro@demo.test", "senha": "senha-de-teste-123"})
    assert r.status_code == 400


def test_open_redirect_bloqueado(cli):
    r = cli.post("/entrar?next=//evil.com", {"email": "pro@demo.test", "senha": "senha-de-teste-123"})
    assert r.status_code == 302 and "evil.com" not in r.headers["Location"]


def test_cadastro_paciente_e_cpf_duplicado(pro, app):
    r = pro.post("/pacientes/novo", {"nome": "Maria da Silva", "cpf": "111.444.777-35", "telefone": "(31) 99999-0000"})
    assert r.status_code == 302
    r = pro.post("/pacientes/novo", {"nome": "Outra Pessoa", "cpf": "11144477735"})
    assert r.status_code == 400 and b"j\xc3\xa1 existe" in r.data.lower()
    p = consulta(app, "SELECT * FROM pacientes")
    assert len(p) == 1 and p[0]["cpf"] == "11144477735" and p[0]["telefone"] == "31999990000"


def test_busca_sem_acento_e_letra(pro):
    pro.post("/pacientes/novo", {"nome": "João Pereira"})
    pro.post("/pacientes/novo", {"nome": "Ana Luíza"})
    assert b"Jo\xc3\xa3o Pereira" in pro.get("/pacientes/?q=joao").data
    r = pro.get("/pacientes/?q=joao")
    assert b"Ana Lu" not in r.data
    r = pro.get("/pacientes/?letra=A")
    assert b"Ana Lu" in r.data and b"Jo\xc3\xa3o Pereira" not in r.data


def test_edicao_gera_auditoria_antes_depois(pro, app):
    pro.post("/pacientes/novo", {"nome": "Carlos Teste", "telefone": "31911112222"})
    pro.post("/pacientes/1/editar", {"nome": "Carlos Teste Jr", "telefone": "31933334444"})
    a = consulta(app, "SELECT detalhes FROM auditoria WHERE acao='editar' AND entidade='pacientes'")
    assert len(a) == 1 and "31911112222" in a[0]["detalhes"] and "31933334444" in a[0]["detalhes"]


def test_auditoria_e_somente_insercao(app):
    import sqlite3
    from app import db as dbmod
    with app.app_context():
        dbmod.auditar("teste", "x", 1, usuario_id=None)
        dbmod.commit()
        for sql in ["UPDATE auditoria SET acao='y'", "DELETE FROM auditoria"]:
            try:
                dbmod.run(sql)
                assert False, "deveria falhar"
            except sqlite3.IntegrityError as e:
                assert "somente de inser" in str(e)


def test_assistente_nao_cria_procedimento(ass):
    assert ass.get("/procedimentos/novo").status_code == 403
    assert ass.post("/procedimentos/novo", {"nome": "X"}).status_code == 403


def test_procedimento_crud_e_nome_duplicado(pro, app):
    assert pro.post("/procedimentos/novo", {"nome": "Peeling (demo)"}).status_code == 302
    r = pro.post("/procedimentos/novo", {"nome": "peeling (DEMO)"})
    assert r.status_code == 200 and b"j\xc3\xa1 existe" in r.data.lower()
    pro.post("/procedimentos/1/alternar")
    assert consulta(app, "SELECT ativo FROM procedimentos")[0]["ativo"] == 0


def test_arquivar_preserva_registro(pro, app):
    pro.post("/pacientes/novo", {"nome": "Paciente Arquivável"})
    pro.post("/pacientes/1/arquivar")
    assert consulta(app, "SELECT ativo FROM pacientes")[0]["ativo"] == 0
    assert "Arquivável" not in pro.get("/pacientes/").get_data(as_text=True)


def test_senha_nova_e_so_admin_cria_usuario(pro, cli, app):
    assert pro.post("/configuracoes/usuarios", {"nome": "x", "email": "x@x.com", "senha": "1234567890"}).status_code == 403
    r = pro.post("/configuracoes", {"atual": "senha-de-teste-123", "nova": "curta", "conf": "curta"})
    assert b"pelo menos 10" in r.data

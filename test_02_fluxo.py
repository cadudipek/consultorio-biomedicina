import re
import sqlite3

import pytest

from conftest import Cli, consulta
from app import db as dbmod

TERMO_TXT = "TERMO DE DEMONSTRAÇÃO. Texto fictício com mais de vinte caracteres para o teste."


def montar_cenario(pro):
    """1 ficha (4 perguntas), 2 termos, 1 procedimento, 1 paciente."""
    pro.post("/modelos/fichas/novo", {"nome": "Anamnese demo"})
    dados = {"nome": "Anamnese demo", "n_campos": "5",
             "c0_rotulo": "Queixa principal", "c0_tipo": "texto_longo", "c0_obrig": "1",
             "c1_rotulo": "Alergias?", "c1_tipo": "sim_nao", "c1_obrig": "1",
             "c2_rotulo": "Pele", "c2_tipo": "escolha_unica", "c2_opcoes": "Seca\nOleosa\nMista",
             "c3_rotulo": "Hábitos", "c3_tipo": "multipla_escolha", "c3_opcoes": "Fuma\nBebe\nExercita-se",
             "c4_rotulo": "Peso (kg)", "c4_tipo": "numero"}
    r = pro.post("/modelos/fichas/1", dados)
    assert r.status_code == 302
    pro.post("/modelos/termos/novo", {"titulo": "Consentimento demo", "tipo": "consentimento", "conteudo": TERMO_TXT})
    pro.post("/modelos/termos/novo", {"titulo": "Imagem demo", "tipo": "imagem", "conteudo": TERMO_TXT + " Imagem."})
    pro.post("/procedimentos/novo", {"nome": "Procedimento demo", "fichas": "1", "termos": ["1", "2"]})
    pro.post("/pacientes/novo", {"nome": "Paciente Fictício", "cpf": "11144477735", "telefone": "31999990000"})
    r = pro.get("/atendimentos/novo?paciente=1&procedimento=1")
    assert r.status_code == 200
    r = pro.post("/atendimentos/novo", {"paciente": "1", "procedimento": "1", "data_atendimento": "2026-11-10"})
    assert r.status_code == 302 and r.headers["Location"].endswith("/atendimentos/1")


def gerar_link(pro, aid=1, horas="72"):
    pro.post(f"/atendimentos/{aid}/links", {"horas": horas})
    html = pro.get(f"/atendimentos/{aid}").get_data(as_text=True)
    m = re.search(r'/p/([\w-]{20,})', html)
    assert m, "link não exibido"
    return m.group(1)


def paciente_cli(app):
    return Cli(app.test_client())  # sem login


FICHA_OK = {"campo_1": "Manchas no rosto", "campo_2": "Não", "campo_3": "Mista", "campo_4": ["Bebe"], "campo_5": "62,5"}


def test_atendimento_fixa_versoes_e_documentos(pro, app):
    montar_cenario(pro)
    docs = consulta(app, "SELECT tipo,status FROM atendimento_documentos ORDER BY id")
    assert [d["tipo"] for d in docs] == ["ficha", "termo", "termo"] and all(d["status"] == "pendente" for d in docs)


def test_ficha_em_uso_gera_nova_versao_sem_alterar_a_antiga(pro, app):
    montar_cenario(pro)
    dados = {"nome": "Anamnese demo", "n_campos": "1", "c0_rotulo": "Pergunta nova", "c0_tipo": "texto"}
    pro.post("/modelos/fichas/1", dados)
    v = consulta(app, "SELECT numero FROM fichas_versao ORDER BY numero")
    assert [x["numero"] for x in v] == [1, 2]
    antigos = consulta(app, "SELECT rotulo FROM ficha_campos WHERE versao_id=1 ORDER BY ordem")
    assert antigos[0]["rotulo"] == "Queixa principal" and len(antigos) == 5


def test_termo_editado_cria_versao_e_atendimento_antigo_mantem_a_sua(pro, app):
    montar_cenario(pro)
    pro.post("/modelos/termos/1", {"titulo": "Consentimento demo", "conteudo": TERMO_TXT + " REVISADO."})
    assert [v["numero"] for v in consulta(app, "SELECT numero FROM termos_versao WHERE termo_id=1 ORDER BY numero")] == [1, 2]
    usado = consulta(app, "SELECT tv.numero FROM atendimento_documentos d JOIN termos_versao tv ON tv.id=d.termo_versao_id WHERE d.id=2")
    assert usado[0]["numero"] == 1
    with app.app_context():
        with pytest.raises(sqlite3.IntegrityError):
            dbmod.run("UPDATE termos_versao SET conteudo='x' WHERE id=1")


def test_fluxo_completo_do_paciente(pro, app):
    montar_cenario(pro)
    token = gerar_link(pro)
    pac = paciente_cli(app)
    r = pac.get(f"/p/{token}")
    assert r.status_code == 200 and b"Paciente" in r.data and b"Anamnese demo" in r.data
    # obrigatórios
    r = pac.post(f"/p/{token}/ficha/1", {"campo_2": "Sim"})
    assert r.status_code == 400 and "obrigatório".encode() in r.data
    # valores inválidos
    r = pac.post(f"/p/{token}/ficha/1", {**FICHA_OK, "campo_5": "abc"})
    assert r.status_code == 400
    r = pac.post(f"/p/{token}/ficha/1", {**FICHA_OK, "campo_3": "Inexistente"})
    assert r.status_code == 400
    assert pac.post(f"/p/{token}/ficha/1", FICHA_OK).status_code == 302
    assert consulta(app, "SELECT status,hash_documento FROM atendimento_documentos WHERE id=1")[0]["status"] == "preenchido"
    # reenvio é bloqueado
    pac.post(f"/p/{token}/ficha/1", {**FICHA_OK, "campo_1": "outra coisa"})
    assert consulta(app, "SELECT valor FROM respostas WHERE campo_id=1")[0]["valor"] == "Manchas no rosto"
    # termo sem aceite / sem nome completo
    assert pac.post(f"/p/{token}/termo/2", {"nome": "Maria", "cpf": "11144477735"}).status_code == 400
    # consentimento assinado
    r = pac.post(f"/p/{token}/termo/2", {"nome": "Maria Fictícia Souza", "cpf": "111.444.777-35", "confirmo": "1"})
    assert r.status_code == 302
    # autorização de imagem: recusa registrada
    assert pac.post(f"/p/{token}/termo/3", {"nome": "Maria Fictícia Souza", "cpf": "11144477735", "confirmo": "1"}).status_code == 400
    assert pac.post(f"/p/{token}/termo/3", {"nome": "Maria Fictícia Souza", "cpf": "11144477735", "confirmo": "1", "decisao": "nao_autorizo"}).status_code == 302
    ass = consulta(app, "SELECT * FROM assinaturas ORDER BY documento_id")
    assert [a["aceite"] for a in ass] == [1, 0]
    assert ass[0]["cpf_signatario"] == "11144477735" and len(ass[0]["hash_documento"]) == 64 and ass[0]["assinado_em"]
    assert "NÃO AUTORIZO" in ass[1]["texto_aceite"]
    # profissional confere
    for did in (1, 2, 3):
        assert b"Integridade verificada" in pro.get(f"/atendimentos/1/documentos/{did}").data
        pro.post(f"/atendimentos/1/documentos/{did}/conferir")
    assert {d["status"] for d in consulta(app, "SELECT status FROM atendimento_documentos")} == {"conferido"}
    assert b"Conclu" in pro.get("/").data and "Tudo em dia".encode() in pro.get("/").data


def test_link_expirado_revogado_e_inexistente(pro, app):
    montar_cenario(pro)
    token = gerar_link(pro)
    pac = paciente_cli(app)
    assert pac.get("/p/token-que-nao-existe-1234567890").status_code == 404
    pro.post("/atendimentos/1/links/1/revogar")
    assert pac.get(f"/p/{token}").status_code == 404
    assert pac.post(f"/p/{token}/ficha/1", FICHA_OK).status_code == 404
    t2 = gerar_link(pro)
    with app.app_context():
        dbmod.run("UPDATE links_acesso SET expira_em='2020-01-01 00:00:00' WHERE id=2")
        dbmod.commit()
    assert pac.get(f"/p/{t2}").status_code == 404


def test_token_nao_fica_no_banco(pro, app):
    montar_cenario(pro)
    token = gerar_link(pro)
    h = consulta(app, "SELECT token_hash FROM links_acesso")[0]["token_hash"]
    assert token not in h and len(h) == 64


def test_link_nao_acessa_documento_de_outro_atendimento(pro, app):
    montar_cenario(pro)
    pro.post("/pacientes/novo", {"nome": "Outro Paciente Fictício"})
    pro.post("/atendimentos/novo", {"paciente": "2", "procedimento": "1", "data_atendimento": "2026-11-11"})
    token_a1 = gerar_link(pro, 1)
    pac = paciente_cli(app)
    # documentos 4,5,6 pertencem ao atendimento 2
    assert pac.get(f"/p/{token_a1}/ficha/4").status_code == 404
    assert pac.post(f"/p/{token_a1}/termo/5", {"nome": "A B", "cpf": "11144477735", "confirmo": "1"}).status_code == 404
    assert "Outro Paciente".encode() not in pac.get(f"/p/{token_a1}").data


def test_respostas_travadas_e_assinatura_imutavel(pro, app):
    montar_cenario(pro)
    token = gerar_link(pro)
    pac = paciente_cli(app)
    pac.post(f"/p/{token}/ficha/1", FICHA_OK)
    pac.post(f"/p/{token}/termo/2", {"nome": "Maria Fictícia Souza", "cpf": "11144477735", "confirmo": "1"})
    with app.app_context():
        for sql in ["UPDATE respostas SET valor='adulterado'", "DELETE FROM respostas",
                    "UPDATE assinaturas SET nome_signatario='Outro'", "DELETE FROM assinaturas"]:
            with pytest.raises(sqlite3.IntegrityError):
                dbmod.run(sql)


def test_adulteracao_e_detectada_pelo_hash(pro, app):
    montar_cenario(pro)
    token = gerar_link(pro)
    paciente_cli(app).post(f"/p/{token}/ficha/1", FICHA_OK)
    with app.app_context():  # simula adulteração direta no arquivo do banco, contornando o trigger
        dbmod.run("DROP TRIGGER trg_resposta_travada_upd")
        dbmod.run("UPDATE respostas SET valor='ADULTERADO' WHERE campo_id=1")
        dbmod.commit()
    r = pro.get("/atendimentos/1/documentos/1")
    assert "foi alterado depois da conclusão".encode() in r.data
    pro.post("/atendimentos/1/documentos/1/conferir")
    assert consulta(app, "SELECT status FROM atendimento_documentos WHERE id=1")[0]["status"] == "preenchido"


def test_adendo_nao_altera_original(pro, app):
    montar_cenario(pro)
    token = gerar_link(pro)
    paciente_cli(app).post(f"/p/{token}/ficha/1", FICHA_OK)
    pro.post("/atendimentos/1/documentos/1/adendo", {"texto": "Paciente informou depois: alergia a látex."})
    assert consulta(app, "SELECT COUNT(*) n FROM adendos")[0]["n"] == 1
    assert b"Integridade verificada" in pro.get("/atendimentos/1/documentos/1").data


def test_profissional_preenche_ficha_presencialmente(pro, app):
    montar_cenario(pro)
    assert pro.post("/atendimentos/1/documentos/1", {"campo_1": "x"}).status_code == 400
    assert pro.post("/atendimentos/1/documentos/1", FICHA_OK).status_code == 302
    assert consulta(app, "SELECT status FROM atendimento_documentos WHERE id=1")[0]["status"] == "preenchido"


def test_assistente_envia_link_mas_nao_ve_conteudo_clinico(pro, ass, app):
    montar_cenario(pro)
    assert ass.get("/atendimentos/1").status_code == 200
    assert ass.post("/atendimentos/1/links", {"horas": "24"}).status_code == 302
    assert ass.get("/atendimentos/1/documentos/1").status_code == 403
    assert ass.post("/atendimentos/1/editar", {"evolucao": "x"}).status_code == 403
    assert ass.get("/modelos/").status_code == 403


def test_evolucao_preserva_texto_anterior_na_auditoria(pro, app):
    montar_cenario(pro)
    pro.post("/atendimentos/1/editar", {"data_atendimento": "2026-11-10", "evolucao": "Primeira evolução"})
    pro.post("/atendimentos/1/editar", {"data_atendimento": "2026-11-10", "evolucao": "Segunda evolução"})
    det = [a["detalhes"] for a in consulta(app, "SELECT detalhes FROM auditoria WHERE entidade='atendimentos' AND acao='editar' ORDER BY id")]
    assert "Primeira evolução" in det[1] and "Segunda evolução" in det[1]


def test_painel_mostra_pendencias(pro, app):
    montar_cenario(pro)
    html = pro.get("/").get_data(as_text=True)
    assert "1 ficha(s) incompleta(s)" in html and "2 termo(s) aguardando assinatura" in html


def test_filtro_por_procedimento(pro):
    montar_cenario(pro)
    pro.post("/pacientes/novo", {"nome": "Sem Atendimento"})
    html = pro.get("/pacientes/?procedimento=1").get_data(as_text=True)
    assert "Paciente Fictício" in html and "Sem Atendimento" not in html

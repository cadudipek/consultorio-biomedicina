import re

from app import db as dbmod


def _ficha_com_detalhe(app, pro):
    pro.post("/modelos-iniciais")
    with app.app_context():
        f = dbmod.q1("SELECT id FROM fichas_modelo WHERE nome LIKE 'Anamnese geral%'")
        v = dbmod.q1("SELECT id FROM fichas_versao WHERE modelo_id=?", (f["id"],))
        campos = dbmod.q("SELECT * FROM ficha_campos WHERE versao_id=? ORDER BY ordem", (v["id"],))
    return campos


def test_alergia_pede_quais(app, pro):
    campos = _ficha_com_detalhe(app, pro)
    alergia = next(c for c in campos if "alergia" in c["rotulo"].lower())
    assert alergia["detalhe"] == "Quais?"
    pro.post("/pacientes/novo", {"nome": "Paciente Fictício", "cpf": "11144477735", "telefone": "31999990000"})
    with app.app_context():
        p = dbmod.q1("SELECT id FROM pacientes")
        pr = dbmod.q1("SELECT id FROM procedimentos WHERE nome LIKE 'Atendimento padrão%'")
    r = pro.post("/atendimentos/novo", {"paciente": p["id"], "procedimento": pr["id"], "data_atendimento": "2026-11-13"})
    with app.app_context():
        d = dbmod.q1("SELECT d.id, d.atendimento_id FROM atendimento_documentos d WHERE tipo='ficha'")
    url = f"/atendimentos/{d['atendimento_id']}/documentos/{d['id']}"
    base = {f"campo_{c['id']}": ("Sim" if c["tipo"] == "sim_nao" else "x") for c in campos if c["tipo"] != "multipla_escolha"}
    # Sim sem detalhe -> erro
    r = pro.post(url, dict(base))
    assert r.status_code == 400 and "Quais?" in r.get_data(as_text=True)
    base[f"detalhe_{alergia['id']}"] = "Dipirona e látex"
    for c in campos:
        if c["tipo"] == "sim_nao" and c["id"] != alergia["id"]:
            base[f"detalhe_{c['id']}"] = "Losartana"
    r = pro.post(url, base)
    assert r.status_code == 302
    html = pro.get(url).get_data(as_text=True)
    assert "Sim — Dipirona e látex" in html
    with app.app_context():
        from app.documentos import verificar_integridade
        assert verificar_integridade(d["id"]) is True

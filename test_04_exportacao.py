import io
import os
import tarfile
import zipfile

from conftest import consulta
from test_02_fluxo import montar_cenario, gerar_link, paciente_cli, FICHA_OK


def concluir_tudo(pro, app):
    token = gerar_link(pro)
    pac = paciente_cli(app)
    pac.post(f"/p/{token}/ficha/1", FICHA_OK)
    pac.post(f"/p/{token}/termo/2", {"nome": "Maria Fictícia Souza", "cpf": "11144477735", "confirmo": "1"})
    pac.post(f"/p/{token}/termo/3", {"nome": "Maria Fictícia Souza", "cpf": "11144477735", "confirmo": "1", "decisao": "autorizo"})


def test_pdf_do_atendimento(pro, app):
    montar_cenario(pro)
    assert pro.get("/atendimentos/1/pdf").status_code == 404  # nada concluído ainda
    concluir_tudo(pro, app)
    r = pro.get("/atendimentos/1/pdf")
    assert r.status_code == 200 and r.mimetype == "application/pdf" and r.data[:5] == b"%PDF-" and len(r.data) > 2000
    assert pro.get("/atendimentos/1/documentos/2/pdf").data[:5] == b"%PDF-"
    assert any(a["acao"] == "exportar_pdf" for a in consulta(app, "SELECT acao FROM auditoria"))


def test_pdf_nao_e_para_assistente(pro, ass, app):
    montar_cenario(pro)
    concluir_tudo(pro, app)
    assert ass.get("/atendimentos/1/pdf").status_code == 403


def test_exportacao_zip_e_protecao_de_formula(pro, app):
    montar_cenario(pro)
    pro.post("/pacientes/novo", {"nome": "=HYPERLINK(\"http://x\")"})
    concluir_tudo(pro, app)
    r = pro.post("/exportacao/dados.zip")
    assert r.status_code == 200
    z = zipfile.ZipFile(io.BytesIO(r.data))
    assert {"pacientes.csv", "atendimentos.csv", "documentos.csv", "respostas_das_fichas.csv", "assinaturas.csv", "arquivos_fotos.csv"} <= set(z.namelist())
    pac = z.read("pacientes.csv").decode("utf-8-sig")
    assert "Paciente Fictício" in pac and "'=HYPERLINK" in pac and ";=HYPERLINK" not in pac
    assert "Manchas no rosto" in z.read("respostas_das_fichas.csv").decode("utf-8-sig")


def test_backup_contem_banco_e_arquivos(app):
    from app.backup import fazer_backup
    with app.app_context():
        os.makedirs(os.path.join(app.config["UPLOAD_DIR"], "1"), exist_ok=True)
        open(os.path.join(app.config["UPLOAD_DIR"], "1", "x.jpg"), "wb").write(b"abc")
        caminho = fazer_backup(app)
    with tarfile.open(caminho) as t:
        nomes = t.getnames()
    assert "consultorio.db" in nomes and any(n.endswith("x.jpg") for n in nomes)


def test_backup_so_admin(pro, app):
    assert pro.post("/exportacao/backup").status_code == 403
    pro.post("/sair")
    pro.login("adm@demo.test")
    assert pro.post("/exportacao/backup").status_code == 302
    assert os.listdir(app.config["BACKUP_DIR"])

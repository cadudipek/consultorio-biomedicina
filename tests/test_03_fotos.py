import io
import os

from PIL import Image

from conftest import consulta
from test_02_fluxo import montar_cenario, paciente_cli, gerar_link, FICHA_OK


def img_bytes(formato="JPEG", cor=(200, 50, 50), exif=False):
    im = Image.new("RGB", (300, 200), cor)
    buf = io.BytesIO()
    kw = {}
    if exif:
        e = Image.Exif()
        e[0x010F] = "FabricanteFake"  # Make
        e[0x8825] = {1: "S", 2: (19.0, 55.0, 0.0)}  # bloco GPS
        kw["exif"] = e
    im.save(buf, formato, **kw)
    return buf.getvalue()


def enviar(pro, dados, nome="f.jpg", **extra):
    form = {"csrf_token": pro.token(), "data_registro": "2026-11-10", "momento": "antes", "atendimento": "1", "arquivo": (io.BytesIO(dados), nome)}
    form.update(extra)
    return pro.c.post("/pacientes/1/fotos", data=form, content_type="multipart/form-data")


def test_upload_valido_remove_exif_e_fica_fora_de_static(pro, app):
    montar_cenario(pro)
    assert enviar(pro, img_bytes(exif=True)).status_code == 302
    f = consulta(app, "SELECT * FROM arquivos")[0]
    caminho = os.path.join(app.config["UPLOAD_DIR"], f["caminho"])
    assert os.path.exists(caminho) and "static" not in caminho
    with Image.open(caminho) as im:
        assert not im.getexif() and "exif" not in im.info
    assert f["nome_original"] == "f.jpg" and f["caminho"].endswith(".jpg") and "f.jpg" not in f["caminho"]


def test_rejeita_arquivo_que_nao_e_imagem(pro, app):
    montar_cenario(pro)
    enviar(pro, b"<?php echo 1; ?>", nome="shell.jpg")
    enviar(pro, b"%PDF-1.4 fake", nome="doc.png")
    assert consulta(app, "SELECT COUNT(*) n FROM arquivos")[0]["n"] == 0


def test_foto_exige_login_e_perfil(pro, ass, app):
    montar_cenario(pro)
    enviar(pro, img_bytes())
    anon = paciente_cli(app)
    assert anon.get("/arquivos/1").status_code == 302        # sem login
    assert anon.get("/pacientes/1/fotos").status_code == 302
    assert ass.get("/arquivos/1").status_code == 403         # assistente
    assert ass.get("/pacientes/1/fotos").status_code == 403
    r = pro.get("/arquivos/1")
    assert r.status_code == 200 and r.mimetype == "image/jpeg" and "no-store" in r.headers["Cache-Control"]


def test_comparar_antes_depois(pro):
    montar_cenario(pro)
    enviar(pro, img_bytes(cor=(10, 10, 200)), momento="antes")
    enviar(pro, img_bytes(cor=(10, 200, 10)), momento="depois", data_registro="2026-11-20")
    r = pro.get("/pacientes/1/comparar?antes=1&depois=2")
    assert r.status_code == 200 and b"Antes" in r.data and b"Depois" in r.data
    assert pro.get("/pacientes/1/comparar?antes=1&depois=99").status_code == 302


def test_atendimento_de_outro_paciente_e_rejeitado(pro):
    montar_cenario(pro)
    pro.post("/pacientes/novo", {"nome": "Outro Fictício"})
    r = pro.c.post("/pacientes/2/fotos", data={"csrf_token": pro.token(), "data_registro": "2026-11-10", "atendimento": "1",
                                               "arquivo": (io.BytesIO(img_bytes()), "a.jpg")}, content_type="multipart/form-data")
    assert r.status_code == 400


def test_alerta_quando_paciente_nao_autoriza_imagem(pro, app):
    montar_cenario(pro)
    token = gerar_link(pro)
    paciente_cli(app).post(f"/p/{token}/termo/3", {"nome": "Maria Fictícia Souza", "cpf": "11144477735", "confirmo": "1", "decisao": "nao_autorizo"})
    assert "Sem autorização de uso de imagem".encode() in pro.get("/pacientes/1/fotos").data


def test_remocao_fica_na_auditoria(pro, app):
    montar_cenario(pro)
    enviar(pro, img_bytes())
    caminho = os.path.join(app.config["UPLOAD_DIR"], consulta(app, "SELECT caminho FROM arquivos")[0]["caminho"])
    pro.post("/arquivos/1/remover")
    assert not os.path.exists(caminho)
    assert any(a["acao"] == "remover_arquivo" for a in consulta(app, "SELECT acao FROM auditoria"))


def test_paginas_publicas_renderizam(pro, app):
    montar_cenario(pro)
    token = gerar_link(pro)
    pac = paciente_cli(app)
    for u in (f"/p/{token}/ficha/1", f"/p/{token}/termo/2", f"/p/{token}/termo/3"):
        r = pac.get(u)
        assert r.status_code == 200, u
    assert b"Etapa 2 de 2" in pac.get(f"/p/{token}/ficha/1").data
    assert pro.get("/atendimentos/1/documentos/1").status_code == 200  # ficha pendente: formulário
    assert pro.get("/atendimentos/1/documentos/2").status_code == 200  # termo pendente
    assert pro.get("/modelos/").status_code == 200 and pro.get("/modelos/fichas/1").status_code == 200

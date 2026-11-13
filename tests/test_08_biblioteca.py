import io
import re


def test_imprimir_ficha_e_termo_em_branco(pro):
    pro.post("/modelos-iniciais")
    html = pro.get("/modelos/").get_data(as_text=True)
    assert "Imprimir em branco" in html
    fid = re.search(r"/modelos/fichas/(\d+)/imprimir", html).group(1)
    tid = re.search(r"/modelos/termos/(\d+)/imprimir", html).group(1)
    for url in (f"/modelos/fichas/{fid}/imprimir", f"/modelos/termos/{tid}/imprimir"):
        r = pro.get(url)
        assert r.status_code == 200 and "Assinatura da paciente" in r.get_data(as_text=True)


def test_biblioteca_upload_abrir_remover(pro):
    r = pro.post("/biblioteca/", {"titulo": "Ficha facial", "categoria": "ficha",
                                  "arquivo": (io.BytesIO(b"%PDF-1.4 teste"), "ficha.pdf")},
                 content_type="multipart/form-data", follow_redirects=True)
    html = r.get_data(as_text=True)
    assert "Ficha facial" in html
    bid = re.search(r"/biblioteca/(\d+)/abrir", html).group(1)
    r = pro.get(f"/biblioteca/{bid}/abrir")
    assert r.status_code == 200 and r.mimetype == "application/pdf"
    for nome, dados in (("x.pdf", b"nao sou pdf"), ("x.exe", b"MZ....")):
        r = pro.post("/biblioteca/", {"arquivo": (io.BytesIO(dados), nome)},
                     content_type="multipart/form-data", follow_redirects=True)
        assert "x.exe" not in r.get_data(as_text=True) and "x.pdf" not in r.get_data(as_text=True)
    pro.post(f"/biblioteca/{bid}/remover")
    assert pro.get(f"/biblioteca/{bid}/abrir").status_code == 404


def test_biblioteca_bloqueada_para_assistente(ass):
    assert ass.get("/biblioteca/").status_code in (302, 403)

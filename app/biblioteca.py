"""Biblioteca de modelos: a profissional sobe fichas/termos que já usa (PDF, Word, imagem),
organiza e imprime. Os arquivos ficam em uploads/biblioteca e só saem por rota autenticada."""
import hashlib
import os
import secrets

from flask import Blueprint, abort, current_app, flash, redirect, render_template, request, send_file, url_for

from .db import auditar, commit, q, q1, run
from .seguranca import login_required

bp = Blueprint("biblioteca", __name__, url_prefix="/biblioteca")

CATEGORIAS = {"ficha": "Ficha de anamnese", "termo": "Termo", "outro": "Outro documento"}
# extensão -> (mime, assinatura inicial do arquivo)
TIPOS = {
    ".pdf": ("application/pdf", (b"%PDF",)),
    ".docx": ("application/vnd.openxmlformats-officedocument.wordprocessingml.document", (b"PK\x03\x04",)),
    ".odt": ("application/vnd.oasis.opendocument.text", (b"PK\x03\x04",)),
    ".png": ("image/png", (b"\x89PNG",)),
    ".jpg": ("image/jpeg", (b"\xff\xd8\xff",)),
    ".jpeg": ("image/jpeg", (b"\xff\xd8\xff",)),
}
ABRE_NO_APP = {".pdf", ".png", ".jpg", ".jpeg"}  # o resto é baixado para abrir no Word


def _pasta():
    p = os.path.join(current_app.config["UPLOAD_DIR"], "biblioteca")
    os.makedirs(p, exist_ok=True)
    return p


@bp.route("/", methods=["GET", "POST"])
@login_required("profissional")
def lista():
    if request.method == "POST":
        arq = request.files.get("arquivo")
        titulo = request.form.get("titulo", "").strip()
        categoria = request.form.get("categoria", "ficha")
        if categoria not in CATEGORIAS:
            categoria = "outro"
        if not arq or not arq.filename:
            flash("Escolha um arquivo para enviar.", "erro")
        else:
            nome = os.path.basename(arq.filename.replace("\\", "/"))
            ext = os.path.splitext(nome)[1].lower()
            dados = arq.read()
            if ext not in TIPOS:
                flash("Formato não aceito. Envie PDF, Word (.docx), .odt, PNG ou JPG.", "erro")
            elif not dados or not any(dados.startswith(a) for a in TIPOS[ext][1]):
                flash("O arquivo parece corrompido ou não é do tipo indicado pela extensão.", "erro")
            else:
                rel = f"{secrets.token_hex(16)}{ext}"
                destino = os.path.join(_pasta(), rel)
                with open(destino, "wb") as f:
                    f.write(dados)
                try:
                    os.chmod(destino, 0o600)
                except OSError:
                    pass
                titulo = titulo or os.path.splitext(nome)[0]
                bid = run("INSERT INTO biblioteca (titulo,categoria,nome_original,caminho,mime,tamanho,sha256) VALUES (?,?,?,?,?,?,?)",
                          (titulo[:150], categoria, nome[:200], rel, TIPOS[ext][0], len(dados), hashlib.sha256(dados).hexdigest()))
                auditar("criar", "biblioteca", bid, {"titulo": titulo, "arquivo": nome})
                commit()
                flash("Modelo guardado na biblioteca.", "ok")
                return redirect(url_for("biblioteca.lista"))
    itens = q("SELECT * FROM biblioteca WHERE ativo=1 ORDER BY categoria, titulo")
    return render_template("biblioteca.html", itens=itens, categorias=CATEGORIAS,
                           abre_no_app=lambda i: os.path.splitext(i["caminho"])[1].lower() in ABRE_NO_APP)


@bp.route("/<int:bid>/abrir")
@login_required("profissional")
def abrir(bid):
    i = q1("SELECT * FROM biblioteca WHERE id=? AND ativo=1", (bid,)) or abort(404)
    ext = os.path.splitext(i["caminho"])[1].lower()
    caminho = os.path.join(_pasta(), os.path.basename(i["caminho"]))
    if not os.path.isfile(caminho):
        abort(404)
    baixar = request.args.get("baixar") == "1" or ext not in ABRE_NO_APP
    auditar("abrir", "biblioteca", bid, {"baixar": baixar})
    commit()
    return send_file(caminho, mimetype=i["mime"], as_attachment=baixar, download_name=i["nome_original"])


@bp.route("/<int:bid>/remover", methods=["POST"])
@login_required("profissional")
def remover(bid):
    i = q1("SELECT * FROM biblioteca WHERE id=? AND ativo=1", (bid,)) or abort(404)
    run("UPDATE biblioteca SET ativo=0 WHERE id=?", (bid,))  # fica guardado no backup; só some da lista
    auditar("remover", "biblioteca", bid, {"titulo": i["titulo"]})
    commit()
    flash("Modelo removido da biblioteca.", "ok")
    return redirect(url_for("biblioteca.lista"))

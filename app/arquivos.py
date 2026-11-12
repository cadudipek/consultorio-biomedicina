"""Fotos por paciente/atendimento. Os arquivos ficam em instance/uploads (fora de static/)
e só saem por rota autenticada."""
import hashlib
import io
import os
import secrets
from datetime import datetime

from flask import Blueprint, abort, current_app, flash, g, redirect, render_template, request, send_file, url_for
from PIL import Image, ImageOps, UnidentifiedImageError

from .db import auditar, commit, q, q1, run
from .seguranca import login_required

bp = Blueprint("arquivos", __name__)

Image.MAX_IMAGE_PIXELS = 50_000_000  # protege contra "bomba de descompressão"
MAX_LADO = 2400


def salvar_imagem(dados: bytes, paciente_id: int):
    """Valida que é imagem de verdade, corrige rotação, REMOVE metadados (EXIF/GPS) e regrava como JPEG.
    Devolve dict com caminho relativo, mime, tamanho e sha256."""
    try:
        img = Image.open(io.BytesIO(dados))
        img.verify()
        img = Image.open(io.BytesIO(dados))
        if img.format not in ("JPEG", "PNG", "WEBP"):
            raise ValueError("formato não permitido")
        img = ImageOps.exif_transpose(img)
    except (UnidentifiedImageError, ValueError, OSError, Image.DecompressionBombError):
        raise ValueError("Envie uma imagem JPG, PNG ou WEBP válida.")
    if img.mode in ("RGBA", "LA", "P"):
        fundo = Image.new("RGB", img.size, (255, 255, 255))
        img = img.convert("RGBA")
        fundo.paste(img, mask=img.split()[-1])
        img = fundo
    else:
        img = img.convert("RGB")
    img.thumbnail((MAX_LADO, MAX_LADO))
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=88, optimize=True)  # sem exif: não é repassado
    conteudo = buf.getvalue()
    rel = f"{paciente_id}/{secrets.token_hex(16)}.jpg"
    destino = os.path.join(current_app.config["UPLOAD_DIR"], rel)
    os.makedirs(os.path.dirname(destino), exist_ok=True)
    with open(destino, "wb") as f:
        f.write(conteudo)
    os.chmod(destino, 0o600)
    return {"caminho": rel, "mime": "image/jpeg", "tamanho": len(conteudo), "sha256": hashlib.sha256(conteudo).hexdigest()}


def _recusas_de_imagem(pid):
    return q("SELECT a.id AS atendimento_id, a.data_atendimento FROM assinaturas s "
             "JOIN atendimento_documentos d ON d.id=s.documento_id JOIN atendimentos a ON a.id=d.atendimento_id "
             "JOIN termos_versao tv ON tv.id=d.termo_versao_id JOIN termos_modelo t ON t.id=tv.termo_id "
             "WHERE a.paciente_id=? AND t.tipo='imagem' AND s.aceite=0", (pid,))


@bp.route("/atendimentos/<int:aid>/fotos")
@login_required("profissional")
def fotos_atendimento(aid):
    a = q1("SELECT paciente_id FROM atendimentos WHERE id=?", (aid,)) or abort(404)
    return redirect(url_for("arquivos.fotos", pid=a["paciente_id"], atendimento=aid))


@bp.route("/pacientes/<int:pid>/fotos", methods=["GET", "POST"])
@login_required("profissional")
def fotos(pid):
    p = q1("SELECT * FROM pacientes WHERE id=?", (pid,)) or abort(404)
    filtro = request.args.get("atendimento", type=int)
    atends = q("SELECT a.id, a.data_atendimento, pr.nome AS procedimento FROM atendimentos a "
               "JOIN procedimentos pr ON pr.id=a.procedimento_id WHERE a.paciente_id=? ORDER BY a.data_atendimento DESC", (pid,))
    if request.method == "POST":
        arq = request.files.get("arquivo")
        aid = request.form.get("atendimento", type=int)
        momento = request.form.get("momento", "outro")
        data = request.form.get("data_registro", "")
        try:
            datetime.strptime(data, "%Y-%m-%d")
        except ValueError:
            data = None
        if momento not in ("antes", "depois", "outro"):
            momento = "outro"
        if aid and not q1("SELECT 1 FROM atendimentos WHERE id=? AND paciente_id=?", (aid, pid)):
            abort(400, "Atendimento não pertence a este paciente.")
        if not arq or not arq.filename:
            flash("Escolha uma foto para enviar.", "erro")
        elif not data:
            flash("Informe a data da foto.", "erro")
        else:
            try:
                info = salvar_imagem(arq.read(), pid)
            except ValueError as e:
                flash(str(e), "erro")
            else:
                fid = run("INSERT INTO arquivos (paciente_id,atendimento_id,nome_original,caminho,mime,tamanho,sha256,descricao,data_registro,momento,criado_por) "
                          "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                          (pid, aid, os.path.basename(arq.filename)[:120], info["caminho"], info["mime"], info["tamanho"], info["sha256"],
                           request.form.get("descricao", "").strip()[:300] or None, data, momento, g.user["id"]))
                auditar("anexar", "arquivos", fid, {"paciente": pid, "atendimento": aid, "sha256": info["sha256"]})
                commit()
                flash("Foto salva.", "ok")
        return redirect(url_for("arquivos.fotos", pid=pid, atendimento=filtro or aid or None))
    sql = "SELECT * FROM arquivos WHERE paciente_id=?"
    args = [pid]
    if filtro:
        sql += " AND atendimento_id=?"
        args.append(filtro)
    lista = q(sql + " ORDER BY data_registro DESC, id DESC", args)
    todas = q("SELECT id, data_registro, momento, descricao FROM arquivos WHERE paciente_id=? ORDER BY data_registro, id", (pid,))
    auditar("visualizar_fotos", "pacientes", pid)
    commit()
    from .atendimentos import hoje_local
    return render_template("pacientes/fotos.html", p=p, lista=lista, todas=todas, atends=atends, filtro=filtro,
                           recusas=_recusas_de_imagem(pid), hoje=hoje_local())


@bp.route("/pacientes/<int:pid>/comparar")
@login_required("profissional")
def comparar(pid):
    p = q1("SELECT * FROM pacientes WHERE id=?", (pid,)) or abort(404)
    ids = [request.args.get("antes", type=int), request.args.get("depois", type=int)]
    fotos_ = []
    for i in ids:
        f = q1("SELECT * FROM arquivos WHERE id=? AND paciente_id=?", (i, pid)) if i else None
        if not f:
            flash("Escolha duas fotos deste paciente para comparar.", "erro")
            return redirect(url_for("arquivos.fotos", pid=pid))
        fotos_.append(f)
    return render_template("pacientes/comparar.html", p=p, antes=fotos_[0], depois=fotos_[1])


@bp.route("/arquivos/<int:fid>")
@login_required("profissional")
def baixar(fid):
    f = q1("SELECT * FROM arquivos WHERE id=?", (fid,)) or abort(404)
    base = os.path.realpath(current_app.config["UPLOAD_DIR"])
    caminho = os.path.realpath(os.path.join(base, f["caminho"]))
    if not caminho.startswith(base + os.sep) or not os.path.exists(caminho):
        abort(404)
    resp = send_file(caminho, mimetype=f["mime"], download_name=f"foto-{fid}.jpg", max_age=0)
    resp.headers["Cache-Control"] = "private, no-store"
    return resp


@bp.route("/arquivos/<int:fid>/remover", methods=["POST"])
@login_required("profissional")
def remover(fid):
    f = q1("SELECT * FROM arquivos WHERE id=?", (fid,)) or abort(404)
    auditar("remover_arquivo", "arquivos", fid, {k: f[k] for k in ("paciente_id", "atendimento_id", "descricao", "data_registro", "sha256")})
    run("DELETE FROM arquivos WHERE id=?", (fid,))
    commit()
    try:
        os.remove(os.path.join(current_app.config["UPLOAD_DIR"], f["caminho"]))
    except OSError:
        pass
    flash("Foto removida. A remoção ficou registrada.", "ok")
    return redirect(url_for("arquivos.fotos", pid=f["paciente_id"]))

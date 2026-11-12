from flask import Blueprint, abort, flash, redirect, render_template, request, url_for

from .db import auditar, commit, q, q1, run
from .seguranca import login_required

bp = Blueprint("procedimentos", __name__, url_prefix="/procedimentos")


def _opcoes():
    fichas = q("SELECT id,nome,demonstracao FROM fichas_modelo WHERE ativo=1 ORDER BY nome")
    termos = q("SELECT id,titulo,tipo,demonstracao FROM termos_modelo WHERE ativo=1 ORDER BY tipo,titulo")
    return fichas, termos


@bp.route("/")
@login_required()
def lista():
    procs = q(
        "SELECT p.*, "
        " (SELECT COUNT(*) FROM procedimento_fichas f WHERE f.procedimento_id=p.id) AS n_fichas, "
        " (SELECT COUNT(*) FROM procedimento_termos t WHERE t.procedimento_id=p.id) AS n_termos "
        "FROM procedimentos p ORDER BY p.ativo DESC, p.nome")
    return render_template("procedimentos/lista.html", procs=procs)


def _salvar(pid, form):
    nome = form.get("nome", "").strip()
    if len(nome) < 2:
        flash("Informe o nome do procedimento.", "erro")
        return None
    dup = q1("SELECT id FROM procedimentos WHERE lower(nome)=lower(?) AND id IS NOT ?", (nome, pid))
    if dup:
        flash("Já existe um procedimento com esse nome.", "erro")
        return None
    desc = form.get("descricao", "").strip() or None
    if pid is None:
        pid = run("INSERT INTO procedimentos (nome,descricao) VALUES (?,?)", (nome, desc))
        auditar("criar", "procedimentos", pid, {"nome": nome})
    else:
        run("UPDATE procedimentos SET nome=?, descricao=? WHERE id=?", (nome, desc, pid))
        auditar("editar", "procedimentos", pid, {"nome": nome})
    fichas = {int(x) for x in form.getlist("fichas") if x.isdigit()}
    termos = {int(x) for x in form.getlist("termos") if x.isdigit()}
    run("DELETE FROM procedimento_fichas WHERE procedimento_id=?", (pid,))
    run("DELETE FROM procedimento_termos WHERE procedimento_id=?", (pid,))
    for f in fichas:
        run("INSERT INTO procedimento_fichas VALUES (?,?)", (pid, f))
    for t in termos:
        run("INSERT INTO procedimento_termos VALUES (?,?)", (pid, t))
    auditar("associar_documentos", "procedimentos", pid, {"fichas": sorted(fichas), "termos": sorted(termos)})
    commit()
    return pid


@bp.route("/novo", methods=["GET", "POST"])
@login_required("profissional")
def novo():
    if request.method == "POST":
        pid = _salvar(None, request.form)
        if pid:
            flash("Procedimento cadastrado.", "ok")
            return redirect(url_for("procedimentos.lista"))
    fichas, termos = _opcoes()
    return render_template("procedimentos/form.html", proc=request.form or {}, fichas=fichas, termos=termos,
                           sel_f=set(), sel_t=set(), novo=True)


@bp.route("/<int:pid>/editar", methods=["GET", "POST"])
@login_required("profissional")
def editar(pid):
    proc = q1("SELECT * FROM procedimentos WHERE id=?", (pid,)) or abort(404)
    if request.method == "POST":
        if _salvar(pid, request.form):
            flash("Procedimento atualizado.", "ok")
            return redirect(url_for("procedimentos.lista"))
    fichas, termos = _opcoes()
    sel_f = {r[0] for r in q("SELECT ficha_modelo_id FROM procedimento_fichas WHERE procedimento_id=?", (pid,))}
    sel_t = {r[0] for r in q("SELECT termo_id FROM procedimento_termos WHERE procedimento_id=?", (pid,))}
    return render_template("procedimentos/form.html", proc=proc, fichas=fichas, termos=termos,
                           sel_f=sel_f, sel_t=sel_t, novo=False, pid=pid)


@bp.route("/<int:pid>/alternar", methods=["POST"])
@login_required("profissional")
def alternar(pid):
    q1("SELECT id FROM procedimentos WHERE id=?", (pid,)) or abort(404)
    run("UPDATE procedimentos SET ativo=1-ativo WHERE id=?", (pid,))
    auditar("alternar_ativo", "procedimentos", pid)
    commit()
    return redirect(url_for("procedimentos.lista"))

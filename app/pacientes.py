from flask import Blueprint, abort, flash, g, redirect, render_template, request, url_for

from .db import auditar, commit, normalizar, q, q1, run, so_digitos
from .seguranca import login_required

bp = Blueprint("pacientes", __name__, url_prefix="/pacientes")


def _validar(form, paciente_id=None):
    nome = form.get("nome", "").strip()
    cpf = so_digitos(form.get("cpf", ""))
    erros = []
    if len(nome) < 3:
        erros.append("Informe o nome completo.")
    if cpf:
        if len(cpf) != 11:
            erros.append("O CPF deve ter 11 números.")
        else:
            outro = q1("SELECT id FROM pacientes WHERE cpf=? AND id IS NOT ?", (cpf, paciente_id))
            if outro:
                erros.append("Já existe um paciente com esse CPF.")
    email = form.get("email", "").strip()
    if email and "@" not in email:
        erros.append("E-mail inválido.")
    nasc = form.get("data_nascimento", "").strip()
    return erros, {
        "nome": nome,
        "nome_busca": normalizar(nome),
        "cpf": cpf or None,
        "data_nascimento": nasc or None,
        "telefone": so_digitos(form.get("telefone", "")) or None,
        "email": email or None,
        "observacoes": form.get("observacoes", "").strip() or None,
    }


@bp.route("/")
@login_required()
def lista():
    termo = normalizar(request.args.get("q", ""))
    proc = request.args.get("procedimento", type=int)
    letra = request.args.get("letra", "").upper()[:1]
    sql = "SELECT p.* FROM pacientes p WHERE p.ativo=1"
    args = []
    if termo:
        sql += " AND (p.nome_busca LIKE ? OR p.cpf LIKE ?)"
        args += [f"%{termo}%", f"%{so_digitos(termo) or '#'}%"]
    if letra and letra.isalpha():
        sql += " AND p.nome_busca LIKE ?"
        args.append(f"{letra.lower()}%")
    if proc:
        sql += " AND p.id IN (SELECT paciente_id FROM atendimentos WHERE procedimento_id=?)"
        args.append(proc)
    sql += " ORDER BY p.nome_busca"
    pacientes = q(sql, args)
    procs = q("SELECT id,nome FROM procedimentos WHERE ativo=1 ORDER BY nome")
    return render_template("pacientes/lista.html", pacientes=pacientes, procs=procs,
                           termo=request.args.get("q", ""), proc=proc, letra=letra)


@bp.route("/novo", methods=["GET", "POST"])
@login_required()
def novo():
    if request.method == "POST":
        erros, d = _validar(request.form)
        if erros:
            for e in erros:
                flash(e, "erro")
            return render_template("pacientes/form.html", p=request.form, novo=True), 400
        pid = run(
            "INSERT INTO pacientes (nome,nome_busca,cpf,data_nascimento,telefone,email,observacoes) "
            "VALUES (:nome,:nome_busca,:cpf,:data_nascimento,:telefone,:email,:observacoes)", d)
        auditar("criar", "pacientes", pid, {"nome": d["nome"]})
        commit()
        flash("Paciente cadastrado.", "ok")
        return redirect(url_for("pacientes.perfil", pid=pid))
    return render_template("pacientes/form.html", p={}, novo=True)


@bp.route("/<int:pid>/editar", methods=["GET", "POST"])
@login_required()
def editar(pid):
    atual = q1("SELECT * FROM pacientes WHERE id=?", (pid,)) or abort(404)
    if request.method == "POST":
        erros, d = _validar(request.form, pid)
        if erros:
            for e in erros:
                flash(e, "erro")
            return render_template("pacientes/form.html", p=request.form, novo=False, pid=pid), 400
        antes = {k: atual[k] for k in d if k != "nome_busca"}
        depois = {k: v for k, v in d.items() if k != "nome_busca"}
        d["id"] = pid
        run("UPDATE pacientes SET nome=:nome,nome_busca=:nome_busca,cpf=:cpf,data_nascimento=:data_nascimento,"
            "telefone=:telefone,email=:email,observacoes=:observacoes,atualizado_em=datetime('now') WHERE id=:id", d)
        auditar("editar", "pacientes", pid, {"antes": antes, "depois": depois})
        commit()
        flash("Dados atualizados.", "ok")
        return redirect(url_for("pacientes.perfil", pid=pid))
    return render_template("pacientes/form.html", p=atual, novo=False, pid=pid)


@bp.route("/<int:pid>")
@login_required()
def perfil(pid):
    p = q1("SELECT * FROM pacientes WHERE id=?", (pid,)) or abort(404)
    atends = q(
        "SELECT a.*, pr.nome AS procedimento, "
        " (SELECT COUNT(*) FROM atendimento_documentos d WHERE d.atendimento_id=a.id) AS total_docs, "
        " (SELECT COUNT(*) FROM atendimento_documentos d WHERE d.atendimento_id=a.id AND d.status IN ('assinado','conferido','preenchido')) AS docs_ok "
        "FROM atendimentos a JOIN procedimentos pr ON pr.id=a.procedimento_id "
        "WHERE a.paciente_id=? ORDER BY a.data_atendimento DESC, a.id DESC", (pid,))
    procs = q("SELECT id,nome FROM procedimentos WHERE ativo=1 ORDER BY nome")
    auditar("visualizar", "pacientes", pid)
    commit()
    return render_template("pacientes/perfil.html", p=p, atends=atends, procs=procs)


@bp.route("/<int:pid>/arquivar", methods=["POST"])
@login_required("profissional")
def arquivar(pid):
    q1("SELECT id FROM pacientes WHERE id=?", (pid,)) or abort(404)
    run("UPDATE pacientes SET ativo=0, atualizado_em=datetime('now') WHERE id=?", (pid,))
    auditar("arquivar", "pacientes", pid)
    commit()
    flash("Paciente arquivado. O histórico foi mantido.", "ok")
    return redirect(url_for("pacientes.lista"))

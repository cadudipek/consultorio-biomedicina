from datetime import datetime, timedelta, timezone

from flask import Blueprint, flash, g, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

from .db import auditar, commit, q, q1, run
from .seguranca import login_required

bp = Blueprint("auth", __name__)

MAX_TENTATIVAS = 5
BLOQUEIO_MIN = 10


def _agora():
    return datetime.now(timezone.utc)


def _seguro(destino):
    return destino if destino and destino.startswith("/") and not destino.startswith("//") else None


@bp.route("/entrar", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email", "").lower().strip()
        senha = request.form.get("senha", "")
        u = q1("SELECT * FROM usuarios WHERE email=? AND ativo=1", (email,))
        msg = "E-mail ou senha incorretos."
        if u and u["bloqueado_ate"] and u["bloqueado_ate"] > _agora().strftime("%Y-%m-%d %H:%M:%S"):
            flash("Muitas tentativas. Aguarde alguns minutos e tente de novo.", "erro")
        elif u and check_password_hash(u["senha_hash"], senha):
            run("UPDATE usuarios SET tentativas=0, bloqueado_ate=NULL WHERE id=?", (u["id"],))
            auditar("login", "usuarios", u["id"], usuario_id=u["id"])
            commit()
            session.clear()
            session["user_id"] = u["id"]
            return redirect(_seguro(request.args.get("next")) or url_for("painel.inicio"))
        else:
            if u:
                t = u["tentativas"] + 1
                bloqueio = None
                if t >= MAX_TENTATIVAS:
                    bloqueio = (_agora() + timedelta(minutes=BLOQUEIO_MIN)).strftime("%Y-%m-%d %H:%M:%S")
                    t = 0
                run("UPDATE usuarios SET tentativas=?, bloqueado_ate=? WHERE id=?", (t, bloqueio, u["id"]))
                auditar("login_falhou", "usuarios", u["id"], usuario_id=u["id"])
                commit()
            flash(msg, "erro")
    return render_template("auth/login.html")


@bp.route("/primeiro-acesso", methods=["GET", "POST"])
def primeiro_acesso():
    """Cadastro do primeiro usuário (admin). Só funciona enquanto não existe nenhum usuário."""
    if q1("SELECT 1 FROM usuarios LIMIT 1"):
        return redirect(url_for("auth.login"))
    if request.method == "POST":
        nome = request.form.get("nome", "").strip()
        email = request.form.get("email", "").lower().strip()
        senha, conf = request.form.get("senha", ""), request.form.get("conf", "")
        if not nome or "@" not in email:
            flash("Informe o nome e um e-mail válido.", "erro")
        elif len(senha) < 10:
            flash("A senha precisa ter pelo menos 10 caracteres.", "erro")
        elif senha != conf:
            flash("A confirmação não confere com a senha.", "erro")
        else:
            uid = run("INSERT INTO usuarios (nome,email,senha_hash,papel) VALUES (?,?,?,'admin')",
                      (nome, email, generate_password_hash(senha)))
            auditar("criar_primeiro_usuario", "usuarios", uid, usuario_id=uid)
            commit()
            session.clear()
            session["user_id"] = uid
            return redirect(url_for("painel.inicio"))
    return render_template("auth/primeiro_acesso.html")


@bp.route("/primeiro-acesso/restaurar", methods=["POST"])
def primeiro_acesso_restaurar():
    """Computador novo: restaura um backup antes de criar qualquer usuário."""
    from flask import current_app
    from .backup import BackupInvalido, restaurar
    if q1("SELECT 1 FROM usuarios LIMIT 1"):
        return redirect(url_for("auth.login"))
    f = request.files.get("arquivo")
    if not f or not f.filename:
        flash("Escolha o arquivo de backup.", "erro")
        return redirect(url_for("auth.primeiro_acesso"))
    try:
        restaurar(current_app, f)
    except BackupInvalido as e:
        flash(str(e), "erro")
        return redirect(url_for("auth.primeiro_acesso"))
    session.clear()
    flash("Seus dados foram recuperados. Entre com o seu e-mail e senha de sempre.", "ok")
    return redirect(url_for("auth.login"))


@bp.route("/sair", methods=["POST"])
def logout():
    if g.user:
        auditar("logout", "usuarios", g.user["id"])
        commit()
    session.clear()
    return redirect(url_for("auth.login"))


@bp.route("/configuracoes", methods=["GET", "POST"])
@login_required()
def configuracoes():
    if request.method == "POST":
        atual, nova, conf = (request.form.get(k, "") for k in ("atual", "nova", "conf"))
        if not check_password_hash(g.user["senha_hash"], atual):
            flash("Senha atual incorreta.", "erro")
        elif len(nova) < 10:
            flash("A nova senha precisa ter pelo menos 10 caracteres.", "erro")
        elif nova != conf:
            flash("A confirmação não confere com a nova senha.", "erro")
        else:
            run("UPDATE usuarios SET senha_hash=? WHERE id=?", (generate_password_hash(nova), g.user["id"]))
            auditar("senha_alterada", "usuarios", g.user["id"])
            commit()
            flash("Senha alterada.", "ok")
            return redirect(url_for("auth.configuracoes"))
    usuarios = q("SELECT id,nome,email,papel,ativo FROM usuarios ORDER BY nome") if g.user["papel"] == "admin" else []
    return render_template("auth/configuracoes.html", usuarios=usuarios)


@bp.route("/configuracoes/usuarios", methods=["POST"])
@login_required("admin")
def novo_usuario():
    nome = request.form.get("nome", "").strip()
    email = request.form.get("email", "").lower().strip()
    papel = request.form.get("papel", "assistente")
    senha = request.form.get("senha", "")
    if not nome or "@" not in email or papel not in ("admin", "profissional", "assistente") or len(senha) < 10:
        flash("Preencha nome, e-mail válido, papel e senha com 10+ caracteres.", "erro")
    elif q1("SELECT 1 FROM usuarios WHERE email=?", (email,)):
        flash("Já existe usuário com esse e-mail.", "erro")
    else:
        uid = run(
            "INSERT INTO usuarios (nome,email,senha_hash,papel) VALUES (?,?,?,?)",
            (nome, email, generate_password_hash(senha), papel),
        )
        auditar("criar", "usuarios", uid, {"email": email, "papel": papel})
        commit()
        flash("Usuário criado.", "ok")
    return redirect(url_for("auth.configuracoes"))


@bp.route("/configuracoes/usuarios/<int:uid>/alternar", methods=["POST"])
@login_required("admin")
def alternar_usuario(uid):
    if uid == g.user["id"]:
        flash("Você não pode desativar o próprio acesso.", "erro")
    else:
        run("UPDATE usuarios SET ativo = 1-ativo WHERE id=?", (uid,))
        auditar("alternar_ativo", "usuarios", uid)
        commit()
    return redirect(url_for("auth.configuracoes"))

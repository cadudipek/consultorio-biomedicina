import os
import secrets
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import click
from flask import Flask, render_template

from . import db as dbmod
from .seguranca import carregar_usuario, csrf_token, verificar_csrf

FUSO = ZoneInfo("America/Sao_Paulo")


def _fmt_dt(valor, formato="%d/%m/%Y %H:%M"):
    """Converte 'YYYY-MM-DD HH:MM:SS' (UTC) para horário de Brasília."""
    if not valor:
        return ""
    try:
        dt = datetime.strptime(valor[:19], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
        return dt.astimezone(FUSO).strftime(formato)
    except ValueError:
        return valor


def _fmt_data(valor):
    if not valor:
        return ""
    try:
        return datetime.strptime(valor[:10], "%Y-%m-%d").strftime("%d/%m/%Y")
    except ValueError:
        return valor


def _fmt_cpf(v):
    v = v or ""
    return f"{v[:3]}.{v[3:6]}.{v[6:9]}-{v[9:]}" if len(v) == 11 else v


def create_app(config=None):
    app = Flask(__name__, instance_relative_config=True)
    Path(app.instance_path).mkdir(parents=True, exist_ok=True)

    chave_arq = Path(app.instance_path) / "secret_key"
    if not chave_arq.exists():
        chave_arq.write_text(secrets.token_hex(32))
        chave_arq.chmod(0o600)

    app.config.update(
        SECRET_KEY=os.environ.get("SECRET_KEY") or chave_arq.read_text().strip(),
        DATABASE=os.path.join(app.instance_path, "consultorio.db"),
        UPLOAD_DIR=os.path.join(app.instance_path, "uploads"),
        BACKUP_DIR=os.path.join(app.instance_path, "backups"),
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=os.environ.get("COOKIE_SECURE", "0") == "1",
        MAX_CONTENT_LENGTH=12 * 1024 * 1024,
        LINK_VALIDADE_HORAS=72,
    )
    if config:
        app.config.update(config)
    Path(app.config["UPLOAD_DIR"]).mkdir(parents=True, exist_ok=True)

    if os.environ.get("TRUST_PROXY") == "1":  # atrás de nginx/PaaS: usa o IP e o HTTPS reais
        from werkzeug.middleware.proxy_fix import ProxyFix
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)
    app.config.setdefault("PUBLIC_BASE_URL", os.environ.get("PUBLIC_BASE_URL", ""))

    app.teardown_appcontext(dbmod.close_db)
    app.before_request(carregar_usuario)
    app.before_request(verificar_csrf)
    app.jinja_env.globals["csrf_token"] = csrf_token
    app.jinja_env.filters["dt"] = _fmt_dt
    app.jinja_env.filters["data"] = _fmt_data
    app.jinja_env.filters["cpf"] = _fmt_cpf

    @app.after_request
    def cabecalhos(resp):
        resp.headers["X-Content-Type-Options"] = "nosniff"
        resp.headers["X-Frame-Options"] = "DENY"
        resp.headers["Referrer-Policy"] = "no-referrer"
        resp.headers.setdefault("Cache-Control", "no-store")
        return resp

    from . import auth, pacientes, procedimentos

    for bp in (auth.bp, pacientes.bp, procedimentos.bp):
        app.register_blueprint(bp)

    # Módulos opcionais registrados conforme forem implementados
    for nome in ("modelos", "atendimentos", "publico", "arquivos", "painel", "exportacao"):
        try:
            mod = __import__(f"app.{nome}", fromlist=["bp"])
        except ModuleNotFoundError as e:
            if e.name != f"app.{nome}":
                raise
            continue
        app.register_blueprint(mod.bp)

    @app.errorhandler(403)
    def e403(e):
        return render_template("erro.html", codigo=403, msg="Você não tem permissão para esta página."), 403

    @app.errorhandler(404)
    def e404(e):
        return render_template("erro.html", codigo=404, msg="Página não encontrada."), 404

    @app.errorhandler(400)
    def e400(e):
        return render_template("erro.html", codigo=400, msg=getattr(e, "description", "Requisição inválida.")), 400

    @app.errorhandler(413)
    def e413(e):
        return render_template("erro.html", codigo=413, msg="Arquivo grande demais (máximo 12 MB)."), 413

    @app.cli.command("init-db")
    def init_db_cmd():
        """Cria as tabelas."""
        dbmod.init_db()
        click.echo("Banco criado.")

    @app.cli.command("criar-usuario")
    @click.option("--nome", prompt=True)
    @click.option("--email", prompt=True)
    @click.option("--papel", type=click.Choice(["admin", "profissional", "assistente"]), default="profissional")
    @click.password_option()
    def criar_usuario(nome, email, papel, password):
        """Cria um usuário de acesso."""
        from werkzeug.security import generate_password_hash

        dbmod.init_db()
        dbmod.run(
            "INSERT INTO usuarios (nome,email,senha_hash,papel) VALUES (?,?,?,?)",
            (nome, email.lower().strip(), generate_password_hash(password), papel),
        )
        dbmod.commit()
        click.echo("Usuário criado.")

    @app.cli.command("backup")
    def backup_cmd():
        """Copia o banco e os arquivos para instance/backups/."""
        from .backup import fazer_backup

        click.echo(f"Backup salvo em {fazer_backup(app)}")

    @app.cli.command("seed")
    def seed_cmd():
        """Carrega dados FICTÍCIOS de demonstração."""
        from .seed import carregar

        carregar()
        click.echo("Dados fictícios carregados.")

    return app

"""Consultório: executável de desktop (janela própria, servidor local, dados do usuário)."""
import os
import socket
import sys
import threading
import time
import urllib.request
from pathlib import Path


def pasta_dados(demo):
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / ".local" / "share")
    return str(Path(base) / ("Consultorio-Demonstracao" if demo else "Consultorio"))


def porta_livre():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


REPO = "cadudipek/consultorio-biomedicina"
DOWNLOAD = f"https://github.com/{REPO}/releases/latest/download/Consultorio-Setup.exe"


def _tupla(v):
    try:
        return tuple(int(x) for x in v.lstrip("v").split("."))
    except ValueError:
        return (0,)


def verificar_atualizacao(app):
    """Consulta a última versão publicada; se for mais nova, o app mostra um aviso com o link de download."""
    import json
    from app.versao import VERSAO
    try:
        req = urllib.request.Request(f"https://api.github.com/repos/{REPO}/releases/latest",
                                     headers={"User-Agent": "Consultorio", "Accept": "application/vnd.github+json"})
        with urllib.request.urlopen(req, timeout=8) as r:
            ultima = json.load(r).get("tag_name", "")
        if _tupla(ultima) > _tupla(VERSAO) and VERSAO != "0.0.0":
            app.config["NOVA_VERSAO"] = {"versao": ultima.lstrip("v"), "url": DOWNLOAD}
    except Exception:
        pass  # sem internet: segue normalmente


def main():
    demo = "--demo" in sys.argv
    os.environ["CONSULTORIO_DATA"] = pasta_dados(demo)
    from app import create_app
    from app import db as dbmod

    app = create_app({"PRIMEIRO_ACESSO": not demo, "LINK_REMOTO": False, "DEMO": demo})
    with app.app_context():
        dbmod.init_db()
        if demo and dbmod.q1("SELECT 1 FROM usuarios LIMIT 1") is None:
            from app.seed import carregar
            carregar()

    threading.Thread(target=verificar_atualizacao, args=(app,), daemon=True).start()

    porta = int(os.environ.get("CONSULTORIO_PORTA") or porta_livre())
    url = f"http://127.0.0.1:{porta}/"

    from waitress import serve
    threading.Thread(target=lambda: serve(app, host="127.0.0.1", port=porta, threads=4), daemon=True).start()
    for _ in range(100):  # espera o servidor responder
        try:
            urllib.request.urlopen(url + "entrar", timeout=1)
            break
        except Exception:
            time.sleep(0.1)

    titulo = "Consultório (demonstração)" if demo else "Consultório"
    try:
        import webview
        webview.settings["ALLOW_DOWNLOADS"] = True  # PDFs, exportação e backup
        webview.create_window(titulo, url, width=1200, height=820, min_size=(420, 600))
        webview.start()
    except Exception:  # sem WebView2: abre no navegador e mantém o servidor vivo
        import webbrowser
        webbrowser.open(url)
        while True:
            time.sleep(3600)


if __name__ == "__main__":
    main()

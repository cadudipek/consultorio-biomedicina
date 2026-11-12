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


def main():
    demo = "--demo" in sys.argv
    os.environ["CONSULTORIO_DATA"] = pasta_dados(demo)
    from app import create_app
    from app import db as dbmod

    app = create_app({"PRIMEIRO_ACESSO": not demo, "LINK_REMOTO": False})
    with app.app_context():
        dbmod.init_db()
        if demo and dbmod.q1("SELECT 1 FROM usuarios LIMIT 1") is None:
            from app.seed import carregar
            carregar()

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
        webview.create_window(titulo, url, width=1200, height=820, min_size=(420, 600))
        webview.start()
    except Exception:  # sem WebView2: abre no navegador e mantém o servidor vivo
        import webbrowser
        webbrowser.open(url)
        while True:
            time.sleep(3600)


if __name__ == "__main__":
    main()

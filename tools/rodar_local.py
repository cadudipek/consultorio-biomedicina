"""Ferramenta do autor: sobe o sistema numa pasta de dados temporária (com ou sem dados fictícios).
Uso: python -m tools.rodar_local PASTA PORTA [--dados]"""
import os
import sys

pasta, porta, com_dados = sys.argv[1], int(sys.argv[2]), "--dados" in sys.argv
os.environ["CONSULTORIO_DATA"] = pasta
from app import create_app, db as dbmod  # noqa: E402

app = create_app({"PRIMEIRO_ACESSO": not com_dados, "LINK_REMOTO": False})
with app.app_context():
    dbmod.init_db()
    if com_dados and dbmod.q1("SELECT 1 FROM usuarios LIMIT 1") is None:
        from tools.demo_seed import carregar
        carregar()
from waitress import serve  # noqa: E402

serve(app, host="127.0.0.1", port=porta, threads=4)

import os
import sqlite3
import tarfile
import tempfile
from datetime import datetime

MANTER = 14  # quantidade de backups guardados


def fazer_backup(app):
    """Cópia consistente do banco (API de backup do SQLite) + pasta de fotos, em um .tar.gz."""
    pasta = app.config["BACKUP_DIR"]
    os.makedirs(pasta, exist_ok=True)
    carimbo = datetime.now().strftime("%Y%m%d-%H%M%S")
    destino = os.path.join(pasta, f"backup-{carimbo}.tar.gz")
    with tempfile.TemporaryDirectory() as tmp:
        copia = os.path.join(tmp, "consultorio.db")
        origem = sqlite3.connect(app.config["DATABASE"])
        alvo = sqlite3.connect(copia)
        with alvo:
            origem.backup(alvo)
        alvo.close()
        origem.close()
        with tarfile.open(destino, "w:gz") as tar:
            tar.add(copia, arcname="consultorio.db")
            if os.path.isdir(app.config["UPLOAD_DIR"]):
                tar.add(app.config["UPLOAD_DIR"], arcname="uploads")
    os.chmod(destino, 0o600)
    antigos = sorted(f for f in os.listdir(pasta) if f.startswith("backup-") and f.endswith(".tar.gz"))
    for f in antigos[:-MANTER]:
        os.remove(os.path.join(pasta, f))
    return destino


def listar_backups(app):
    pasta = app.config["BACKUP_DIR"]
    if not os.path.isdir(pasta):
        return []
    itens = []
    for f in sorted(os.listdir(pasta), reverse=True):
        if f.startswith("backup-") and f.endswith(".tar.gz"):
            itens.append({"nome": f, "kb": os.path.getsize(os.path.join(pasta, f)) // 1024})
    return itens

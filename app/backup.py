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
    n = 2
    while os.path.exists(destino):  # nunca sobrescreve uma cópia anterior
        destino = os.path.join(pasta, f"backup-{carimbo}-{n}.tar.gz")
        n += 1
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


class BackupInvalido(Exception):
    pass


def restaurar(app, arquivo):
    """Substitui o banco e as fotos pelo conteúdo de um backup .tar.gz gerado por fazer_backup.
    Valida o arquivo antes de tocar em qualquer dado. Se já houver dados, guarda uma cópia antes."""
    import shutil
    from flask import g

    with tempfile.TemporaryDirectory() as tmp:
        bruto = os.path.join(tmp, "enviado.tar.gz")
        arquivo.save(bruto)
        try:
            tar = tarfile.open(bruto, "r:gz")
        except (tarfile.TarError, OSError):
            raise BackupInvalido("O arquivo não é um backup deste sistema (esperado: backup-AAAAMMDD-HHMMSS.tar.gz).")
        with tar:
            membros = tar.getmembers()
            nomes = {m.name for m in membros}
            if "consultorio.db" not in nomes:
                raise BackupInvalido("O arquivo não contém o banco de dados do sistema.")
            for m in membros:
                ok_nome = m.name == "consultorio.db" or m.name == "uploads" or m.name.startswith("uploads/")
                if not ok_nome or ".." in m.name.split("/") or m.name.startswith("/") or not (m.isfile() or m.isdir()):
                    raise BackupInvalido("O backup contém itens inesperados e foi recusado por segurança.")
            destino = os.path.join(tmp, "x")
            os.makedirs(destino)
            for m in membros:
                alvo = os.path.join(destino, *m.name.split("/"))
                if m.isdir():
                    os.makedirs(alvo, exist_ok=True)
                else:
                    os.makedirs(os.path.dirname(alvo), exist_ok=True)
                    with tar.extractfile(m) as src, open(alvo, "wb") as dst:
                        shutil.copyfileobj(src, dst)
        novo_db = os.path.join(destino, "consultorio.db")
        try:
            c = sqlite3.connect(novo_db)
            ok = c.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
            tem_tabela = c.execute("SELECT 1 FROM sqlite_master WHERE name='usuarios'").fetchone()
            c.close()
        except sqlite3.DatabaseError:
            ok, tem_tabela = False, None
        if not ok or not tem_tabela:
            raise BackupInvalido("O banco de dados dentro do backup está danificado.")

        # cópia de segurança do estado atual (se houver dados)
        if os.path.exists(app.config["DATABASE"]):
            c = sqlite3.connect(app.config["DATABASE"])
            tem_dados = c.execute("SELECT 1 FROM sqlite_master WHERE name='usuarios'").fetchone() and \
                c.execute("SELECT 1 FROM usuarios LIMIT 1").fetchone()
            c.close()
            if tem_dados:
                fazer_backup(app)

        db = g.pop("db", None)
        if db is not None:
            db.close()
        shutil.copyfile(novo_db, app.config["DATABASE"])
        up = app.config["UPLOAD_DIR"]
        if os.path.isdir(up):
            shutil.rmtree(up)
        if os.path.isdir(os.path.join(destino, "uploads")):
            shutil.copytree(os.path.join(destino, "uploads"), up)
        else:
            os.makedirs(up, exist_ok=True)

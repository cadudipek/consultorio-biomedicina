"""Dados FICTÍCIOS para demonstração. Nada aqui é conteúdo clínico real:
os textos de termos e fichas são marcados como EXEMPLO e devem ser substituídos pelos da profissional."""
import io
import json

from PIL import Image, ImageDraw
from werkzeug.security import generate_password_hash

from . import db as d
from .arquivos import salvar_imagem
from .documentos import assinar_termo, campos_da_versao, concluir_ficha, documento_completo, sha256

SENHA_DEMO = "demonstracao-123"

TERMO_CONSENT = """TERMO DE CONSENTIMENTO — EXEMPLO (DEMONSTRAÇÃO)

[Texto fictício. Substituir pelo documento fornecido pela profissional.]

Declaro que fui informado(a), em linguagem clara, sobre o procedimento a ser realizado, seus objetivos, cuidados antes e depois e possíveis intercorrências. Tive a oportunidade de esclarecer minhas dúvidas e concordo em realizá-lo."""

TERMO_IMAGEM = """AUTORIZAÇÃO DE USO DE IMAGEM — EXEMPLO (DEMONSTRAÇÃO)

[Texto fictício. Substituir pelo documento fornecido pela profissional.]

Esta autorização é independente do consentimento do procedimento. Escolho, abaixo, se autorizo ou não o uso das minhas imagens (fotos antes e depois) para fins de divulgação. A recusa não impede a realização do atendimento."""

CAMPOS_ANAMNESE = [
    ("Queixa principal (exemplo)", "texto_longo", 1, None),
    ("Possui alguma alergia?", "sim_nao", 1, None, "Quais?"),
    ("Tipo de pele (exemplo)", "escolha_unica", 0, ["Seca", "Oleosa", "Mista", "Normal"]),
    ("Hábitos (exemplo)", "multipla_escolha", 0, ["Fuma", "Consome álcool", "Pratica exercícios", "Usa protetor solar"]),
    ("Peso (kg)", "numero", 0, None),
    ("Data da última consulta", "data", 0, None),
]

PACIENTES = [
    ("Ana Beatriz Exemplo", "00000000001", "1990-03-12", "31900000001"),
    ("Bruno Carvalho Teste", "00000000002", "1985-07-30", "31900000002"),
    ("Carla Mendes Fictícia", "00000000003", "1978-11-05", "31900000003"),
    ("Daniel Souza Demonstração", "00000000004", "1995-01-22", "31900000004"),
    ("Érica Lima Simulada", "00000000005", "2000-09-17", "31900000005"),
]


def _foto(texto, cor):
    im = Image.new("RGB", (900, 700), cor)
    dr = ImageDraw.Draw(im)
    dr.ellipse((250, 120, 650, 560), outline=(255, 255, 255), width=6)
    dr.text((40, 40), f"{texto}", fill=(255, 255, 255))
    dr.text((40, 70), "IMAGEM FICTÍCIA — DEMONSTRAÇÃO", fill=(255, 255, 255))
    buf = io.BytesIO()
    im.save(buf, "JPEG")
    return buf.getvalue()


def carregar():
    d.init_db()  # idempotente (CREATE ... IF NOT EXISTS)
    if d.q1("SELECT 1 FROM usuarios LIMIT 1"):
        raise SystemExit("O banco já tem usuários. O seed é só para bancos de demonstração vazios.")
    uid = d.run("INSERT INTO usuarios (nome,email,senha_hash,papel) VALUES (?,?,?,?)",
                ("Dra. Demonstração", "demo@exemplo.test", generate_password_hash(SENHA_DEMO), "admin"))
    d.run("INSERT INTO usuarios (nome,email,senha_hash,papel) VALUES (?,?,?,?)",
          ("Assistente Demonstração", "assistente@exemplo.test", generate_password_hash(SENHA_DEMO), "assistente"))

    # Ficha
    mid = d.run("INSERT INTO fichas_modelo (nome,descricao,demonstracao) VALUES (?,?,1)", ("Anamnese Exemplo (demonstração)", "Modelo fictício"))
    vid = d.run("INSERT INTO fichas_versao (modelo_id,numero) VALUES (?,1)", (mid,))
    for i, (rot, tipo, ob, ops, *det) in enumerate(CAMPOS_ANAMNESE, 1):
        d.run("INSERT INTO ficha_campos (versao_id,ordem,rotulo,tipo,obrigatorio,opcoes,detalhe) VALUES (?,?,?,?,?,?,?)",
              (vid, i, rot, tipo, ob, json.dumps(ops, ensure_ascii=False) if ops else None, det[0] if det else None))
    # Termos
    t1 = d.run("INSERT INTO termos_modelo (titulo,tipo,demonstracao) VALUES (?,?,1)", ("Consentimento — EXEMPLO (demonstração)", "consentimento"))
    d.run("INSERT INTO termos_versao (termo_id,numero,conteudo,hash_conteudo) VALUES (?,1,?,?)", (t1, TERMO_CONSENT, sha256(TERMO_CONSENT)))
    t2 = d.run("INSERT INTO termos_modelo (titulo,tipo,demonstracao) VALUES (?,?,1)", ("Uso de imagem — EXEMPLO (demonstração)", "imagem"))
    d.run("INSERT INTO termos_versao (termo_id,numero,conteudo,hash_conteudo) VALUES (?,1,?,?)", (t2, TERMO_IMAGEM, sha256(TERMO_IMAGEM)))
    # Procedimentos
    procs = []
    for nome in ("Procedimento Exemplo A (demonstração)", "Procedimento Exemplo B (demonstração)"):
        pid = d.run("INSERT INTO procedimentos (nome,descricao,demonstracao) VALUES (?,?,1)", (nome, "Procedimento fictício para demonstração"))
        d.run("INSERT INTO procedimento_fichas VALUES (?,?)", (pid, mid))
        d.run("INSERT INTO procedimento_termos VALUES (?,?)", (pid, t1))
        d.run("INSERT INTO procedimento_termos VALUES (?,?)", (pid, t2))
        procs.append(pid)
    # Pacientes
    ids = []
    for nome, cpf, nasc, tel in PACIENTES:
        ids.append(d.run("INSERT INTO pacientes (nome,nome_busca,cpf,data_nascimento,telefone,email) VALUES (?,?,?,?,?,?)",
                         (nome, d.normalizar(nome), cpf, nasc, tel, f"{d.normalizar(nome).split()[0]}@exemplo.test")))

    def atendimento(paciente, proc, data, obs=None, evol=None):
        aid = d.run("INSERT INTO atendimentos (paciente_id,procedimento_id,data_atendimento,observacoes,evolucao,criado_por) VALUES (?,?,?,?,?,?)",
                    (paciente, proc, data, obs, evol, uid))
        d.run("INSERT INTO atendimento_documentos (atendimento_id,tipo,ficha_versao_id) VALUES (?,'ficha',?)", (aid, vid))
        d.run("INSERT INTO atendimento_documentos (atendimento_id,tipo,termo_versao_id) VALUES (?,'termo',(SELECT MAX(id) FROM termos_versao WHERE termo_id=?))", (aid, t1))
        d.run("INSERT INTO atendimento_documentos (atendimento_id,tipo,termo_versao_id) VALUES (?,'termo',(SELECT MAX(id) FROM termos_versao WHERE termo_id=?))", (aid, t2))
        return aid, [r["id"] for r in d.q("SELECT id FROM atendimento_documentos WHERE atendimento_id=? ORDER BY id", (aid,))]

    def preencher(did, nome_pac, cpf, autoriza=True, conferir=True, so_ficha=False):
        doc = documento_completo(did)
        if doc["tipo"] == "ficha":
            vals = {c["id"]: v for c, v in zip(campos_da_versao(doc["ficha_versao_id"]),
                    ["Queixa de exemplo (fictícia)", "Não", "Mista", json.dumps(["Usa protetor solar"], ensure_ascii=False), "60", "2026-06-10"])}
            concluir_ficha(doc, vals, "demo")
        else:
            tipo = d.q1("SELECT t.tipo FROM termos_versao v JOIN termos_modelo t ON t.id=v.termo_id WHERE v.id=?", (doc["termo_versao_id"],))["tipo"]
            assinar_termo(doc, tipo, nome_pac, cpf, 1 if (tipo == "consentimento" or autoriza) else 0, None, "127.0.0.1", "demo", None)
        if conferir:
            d.run("UPDATE atendimento_documentos SET status='conferido' WHERE id=?", (did,))

    # 1) Atendimento totalmente concluído, com fotos antes/depois
    a1, docs1 = atendimento(ids[0], procs[0], "2026-10-15", "Atendimento de demonstração.", "Evolução de exemplo: sem intercorrências (texto fictício).")
    for did in docs1:
        preencher(did, PACIENTES[0][0], PACIENTES[0][1])
    for momento, data, cor in (("antes", "2026-10-15", (90, 120, 160)), ("depois", "2026-11-05", (80, 150, 120))):
        info = salvar_imagem(_foto(f"{momento.upper()} — {data}", cor), ids[0])
        d.run("INSERT INTO arquivos (paciente_id,atendimento_id,nome_original,caminho,mime,tamanho,sha256,descricao,data_registro,momento,criado_por) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
              (ids[0], a1, f"{momento}.jpg", info["caminho"], info["mime"], info["tamanho"], info["sha256"], f"Foto fictícia ({momento})", data, momento, uid))
    # 2) Ficha preenchida, termos pendentes
    a2, docs2 = atendimento(ids[1], procs[1], "2026-11-10")
    preencher(docs2[0], PACIENTES[1][0], PACIENTES[1][1], conferir=False)
    # 3) Tudo pendente
    atendimento(ids[2], procs[0], "2026-11-12")
    # 4) Paciente que NÃO autorizou uso de imagem
    a4, docs4 = atendimento(ids[3], procs[1], "2026-11-08")
    for did in docs4:
        preencher(did, PACIENTES[3][0], PACIENTES[3][1], autoriza=False, conferir=True)
    d.auditar("seed", "sistema", None, {"obs": "dados fictícios"}, usuario_id=uid)
    d.commit()

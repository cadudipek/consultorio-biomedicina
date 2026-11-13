"""Regras compartilhadas de fichas e termos: validação, conclusão, assinatura e integridade.
Usado pela área da profissional e pela página pública do paciente."""
import base64
import hashlib
import json
from datetime import datetime, timezone

from .db import auditar, q, q1, run, so_digitos

TIPOS = {
    "texto": "Texto curto",
    "texto_longo": "Texto longo",
    "numero": "Número",
    "data": "Data",
    "sim_nao": "Sim ou não",
    "escolha_unica": "Escolha única",
    "multipla_escolha": "Múltipla escolha",
}

TEXTO_ACEITE = {
    "consentimento": "Li e compreendi o termo acima e concordo com a realização do procedimento.",
    "imagem": "Li e compreendi o termo acima e decido sobre o uso das minhas imagens conforme indicado.",
}


def agora_utc():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def sha256(texto):
    return hashlib.sha256(texto.encode("utf-8")).hexdigest()


def canonico(obj):
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def opcoes_do_campo(campo):
    try:
        return json.loads(campo["opcoes"]) if campo["opcoes"] else []
    except ValueError:
        return []


def campos_da_versao(versao_id):
    return q("SELECT * FROM ficha_campos WHERE versao_id=? ORDER BY ordem, id", (versao_id,))


def ler_respostas(campos, form):
    """Converte o formulário em {campo_id: valor} e devolve também a lista de erros."""
    valores, erros = {}, []
    for c in campos:
        nome = f"campo_{c['id']}"
        if c["tipo"] == "multipla_escolha":
            bruto = form.getlist(nome)
            validas = set(opcoes_do_campo(c))
            if any(v not in validas for v in bruto):
                erros.append(f"“{c['rotulo']}”: opção inválida.")
            valor = json.dumps(bruto, ensure_ascii=False) if bruto else ""
        else:
            valor = (form.get(nome) or "").strip()
            if valor:
                if c["tipo"] == "numero":
                    try:
                        float(valor.replace(",", "."))
                    except ValueError:
                        erros.append(f"“{c['rotulo']}”: informe um número.")
                elif c["tipo"] == "data":
                    try:
                        datetime.strptime(valor, "%Y-%m-%d")
                    except ValueError:
                        erros.append(f"“{c['rotulo']}”: data inválida.")
                elif c["tipo"] == "sim_nao" and valor not in ("Sim", "Não"):
                    erros.append(f"“{c['rotulo']}”: escolha Sim ou Não.")
                elif c["tipo"] == "escolha_unica" and valor not in opcoes_do_campo(c):
                    erros.append(f"“{c['rotulo']}”: opção inválida.")
        if c["obrigatorio"] and not valor:
            erros.append(f"“{c['rotulo']}” é obrigatório.")
        if c["tipo"] == "sim_nao" and c["detalhe"]:
            det = (form.get(f"detalhe_{c['id']}") or "").strip()[:500]
            if valor == "Sim" and not det:
                erros.append(f"“{c['rotulo']}”: preencha “{c['detalhe']}”.")
            valores[("d", c["id"])] = det if valor == "Sim" else ""
        valores[c["id"]] = valor
    return valores, erros


def formatar_valor(campo, valor, detalhe=None):
    if not valor:
        return "—"
    if detalhe:
        return f"{valor} — {detalhe}"
    if campo["tipo"] == "multipla_escolha":
        try:
            return ", ".join(json.loads(valor)) or "—"
        except ValueError:
            return valor
    if campo["tipo"] == "data":
        try:
            return datetime.strptime(valor, "%Y-%m-%d").strftime("%d/%m/%Y")
        except ValueError:
            return valor
    return valor


def detalhes_do_documento(doc_id):
    return {r["campo_id"]: r["detalhe"] for r in q("SELECT campo_id,detalhe FROM respostas WHERE documento_id=? AND detalhe IS NOT NULL AND detalhe!=''", (doc_id,))}


def respostas_do_documento(doc_id):
    return {r["campo_id"]: r["valor"] for r in q("SELECT campo_id,valor FROM respostas WHERE documento_id=?", (doc_id,))}


def documento_completo(doc_id):
    return q1(
        "SELECT d.*, a.paciente_id, a.id AS atend_id FROM atendimento_documentos d "
        "JOIN atendimentos a ON a.id=d.atendimento_id WHERE d.id=?", (doc_id,))


# ---------------- Ficha ----------------
def _payload_ficha(doc, valores_por_campo, concluido_em, campos, detalhes=None):
    detalhes = detalhes or {}
    return {
        "tipo": "ficha",
        "atendimento": doc["atendimento_id"],
        "ficha_versao": doc["ficha_versao_id"],
        "concluido_em": concluido_em,
        "respostas": [[c["id"], c["rotulo"], valores_por_campo.get(c["id"], "")] + ([detalhes[c["id"]]] if detalhes.get(c["id"]) else [])
                      for c in campos],
    }


def concluir_ficha(doc, valores, origem):
    """Grava as respostas, trava o documento e registra o hash."""
    campos = campos_da_versao(doc["ficha_versao_id"])
    for c in campos:
        run("INSERT INTO respostas (documento_id,campo_id,valor,detalhe) VALUES (?,?,?,?)",
            (doc["id"], c["id"], valores.get(c["id"], ""), valores.get(("d", c["id"])) or None))
    agora = agora_utc()
    detalhes = {c["id"]: valores.get(("d", c["id"])) for c in campos}
    h = sha256(canonico(_payload_ficha(doc, valores, agora, campos, detalhes)))
    run("UPDATE atendimento_documentos SET status='preenchido', concluido_em=?, hash_documento=? WHERE id=?",
        (agora, h, doc["id"]))
    auditar("ficha_preenchida", "atendimento_documentos", doc["id"], {"origem": origem, "hash": h})


# ---------------- Termo ----------------
def _payload_termo(doc, texto_hash, nome, cpf, aceite, assinado_em, texto_aceite, paciente_id):
    return {
        "tipo": "termo",
        "atendimento": doc["atendimento_id"],
        "paciente": paciente_id,
        "termo_versao": doc["termo_versao_id"],
        "texto_sha256": texto_hash,
        "signatario": nome,
        "cpf": cpf,
        "aceite": aceite,
        "texto_aceite": texto_aceite,
        "assinado_em": assinado_em,
    }


def validar_assinatura(tipo_termo, form):
    erros = []
    nome = (form.get("nome") or "").strip()
    cpf = so_digitos(form.get("cpf"))
    if len(nome.split()) < 2:
        erros.append("Informe seu nome completo.")
    if len(cpf) != 11:
        erros.append("Informe seu CPF com 11 números.")
    if tipo_termo == "imagem":
        decisao = form.get("decisao")
        if decisao not in ("autorizo", "nao_autorizo"):
            erros.append("Escolha se autoriza ou não o uso de imagem.")
        aceite = 1 if decisao == "autorizo" else 0
    else:
        aceite = 1
    if form.get("confirmo") != "1":
        erros.append("Marque a caixa de confirmação para assinar.")
    return erros, nome, cpf, aceite


def assinar_termo(doc, tipo_termo, nome, cpf, aceite, desenho_dataurl, ip, user_agent, link_id):
    versao = q1("SELECT * FROM termos_versao WHERE id=?", (doc["termo_versao_id"],))
    texto_aceite = TEXTO_ACEITE[tipo_termo]
    if tipo_termo == "imagem":
        texto_aceite += " Decisão: " + ("AUTORIZO o uso de imagem." if aceite else "NÃO AUTORIZO o uso de imagem.")
    assinado_em = agora_utc()
    h = sha256(canonico(_payload_termo(doc, versao["hash_conteudo"], nome, cpf, aceite, assinado_em, texto_aceite, doc["paciente_id"])))
    png = None
    if desenho_dataurl and desenho_dataurl.startswith("data:image/png;base64,"):
        try:
            png = base64.b64decode(desenho_dataurl.split(",", 1)[1], validate=True)
            if len(png) > 300_000 or not png.startswith(b"\x89PNG"):
                png = None
        except ValueError:
            png = None
    run("INSERT INTO assinaturas (documento_id,nome_signatario,cpf_signatario,texto_aceite,aceite,assinado_em,ip,user_agent,hash_documento,via_link_id,desenho_png) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (doc["id"], nome, cpf, texto_aceite, aceite, assinado_em, ip, (user_agent or "")[:300], h, link_id, png))
    run("UPDATE atendimento_documentos SET status='assinado', concluido_em=?, hash_documento=? WHERE id=?",
        (assinado_em, h, doc["id"]))
    auditar("termo_assinado", "atendimento_documentos", doc["id"], {"hash": h, "aceite": aceite, "via_link": link_id})


# ---------------- Integridade ----------------
def verificar_integridade(doc_id):
    """True se o hash recalculado confere com o registrado; None se o documento não foi concluído."""
    doc = documento_completo(doc_id)
    if not doc or not doc["hash_documento"]:
        return None
    if doc["tipo"] == "ficha":
        campos = campos_da_versao(doc["ficha_versao_id"])
        valores = respostas_do_documento(doc_id)
        h = sha256(canonico(_payload_ficha(doc, valores, doc["concluido_em"], campos, detalhes_do_documento(doc_id))))
    else:
        a = q1("SELECT * FROM assinaturas WHERE documento_id=?", (doc_id,))
        v = q1("SELECT * FROM termos_versao WHERE id=?", (doc["termo_versao_id"],))
        if not a or not v:
            return False
        texto_hash = sha256(v["conteudo"])
        h = sha256(canonico(_payload_termo(doc, texto_hash, a["nome_signatario"], a["cpf_signatario"], a["aceite"],
                                           a["assinado_em"], a["texto_aceite"], doc["paciente_id"])))
        if texto_hash != v["hash_conteudo"]:
            return False
    return h == doc["hash_documento"]

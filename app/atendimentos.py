import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

from flask import Blueprint, abort, current_app, flash, g, redirect, render_template, request, session, url_for

from .db import auditar, commit, q, q1, run
from .documentos import (campos_da_versao, concluir_ficha, formatar_valor, ler_respostas, opcoes_do_campo,
                         respostas_do_documento, verificar_integridade)
from .seguranca import login_required

bp = Blueprint("atendimentos", __name__, url_prefix="/atendimentos")


def hoje_local():
    from . import FUSO
    return datetime.now(FUSO).strftime("%Y-%m-%d")


def _docs_do_procedimento(proc_id):
    """Última versão de cada ficha e termo ativos associados ao procedimento."""
    fichas = q("SELECT v.id AS versao_id, m.nome FROM procedimento_fichas pf JOIN fichas_modelo m ON m.id=pf.ficha_modelo_id "
               "JOIN fichas_versao v ON v.id=(SELECT id FROM fichas_versao WHERE modelo_id=m.id ORDER BY numero DESC LIMIT 1) "
               "WHERE pf.procedimento_id=? AND m.ativo=1 ORDER BY m.nome", (proc_id,))
    termos = q("SELECT v.id AS versao_id, t.titulo AS nome, t.tipo FROM procedimento_termos pt JOIN termos_modelo t ON t.id=pt.termo_id "
               "JOIN termos_versao v ON v.id=(SELECT id FROM termos_versao WHERE termo_id=t.id ORDER BY numero DESC LIMIT 1) "
               "WHERE pt.procedimento_id=? AND t.ativo=1 ORDER BY t.tipo, t.titulo", (proc_id,))
    return fichas, termos


@bp.route("/novo", methods=["GET", "POST"])
@login_required()
def novo():
    pid = request.values.get("paciente", type=int)
    proc_id = request.values.get("procedimento", type=int)
    paciente = q1("SELECT * FROM pacientes WHERE id=? AND ativo=1", (pid,)) or abort(404)
    proc = q1("SELECT * FROM procedimentos WHERE id=? AND ativo=1", (proc_id,)) or abort(404)
    fichas, termos = _docs_do_procedimento(proc_id)
    if request.method == "POST":
        data = request.form.get("data_atendimento", "")
        try:
            datetime.strptime(data, "%Y-%m-%d")
        except ValueError:
            flash("Informe uma data válida.", "erro")
            return render_template("atendimentos/novo.html", paciente=paciente, proc=proc, fichas=fichas, termos=termos, hoje=data), 400
        aid = run("INSERT INTO atendimentos (paciente_id,procedimento_id,data_atendimento,observacoes,criado_por) VALUES (?,?,?,?,?)",
                  (pid, proc_id, data, request.form.get("observacoes", "").strip() or None, g.user["id"]))
        for f in fichas:
            run("INSERT INTO atendimento_documentos (atendimento_id,tipo,ficha_versao_id) VALUES (?,'ficha',?)", (aid, f["versao_id"]))
        for t in termos:
            run("INSERT INTO atendimento_documentos (atendimento_id,tipo,termo_versao_id) VALUES (?,'termo',?)", (aid, t["versao_id"]))
        auditar("criar", "atendimentos", aid, {"paciente": pid, "procedimento": proc_id, "documentos": len(fichas) + len(termos)})
        commit()
        flash("Atendimento aberto. Agora você pode enviar o link ao paciente.", "ok")
        return redirect(url_for("atendimentos.detalhe", aid=aid))
    return render_template("atendimentos/novo.html", paciente=paciente, proc=proc, fichas=fichas, termos=termos, hoje=hoje_local())


def _atendimento(aid):
    a = q1("SELECT a.*, p.nome AS paciente, p.telefone, p.cpf AS paciente_cpf, pr.nome AS procedimento "
           "FROM atendimentos a JOIN pacientes p ON p.id=a.paciente_id JOIN procedimentos pr ON pr.id=a.procedimento_id WHERE a.id=?", (aid,))
    return a or abort(404)


def _docs(aid):
    return q("SELECT d.*, COALESCE(m.nome, t.titulo) AS nome, t.tipo AS tipo_termo, "
             " COALESCE(fv.numero, tv.numero) AS versao "
             "FROM atendimento_documentos d "
             "LEFT JOIN fichas_versao fv ON fv.id=d.ficha_versao_id LEFT JOIN fichas_modelo m ON m.id=fv.modelo_id "
             "LEFT JOIN termos_versao tv ON tv.id=d.termo_versao_id LEFT JOIN termos_modelo t ON t.id=tv.termo_id "
             "WHERE d.atendimento_id=? ORDER BY d.tipo, t.tipo, d.id", (aid,))


@bp.route("/<int:aid>")
@login_required()
def detalhe(aid):
    a = _atendimento(aid)
    docs = _docs(aid)
    links = q("SELECT * FROM links_acesso WHERE atendimento_id=? ORDER BY id DESC", (aid,))
    agora = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    novo_link = session.pop("novo_link", None)
    wa = None
    if novo_link and a["telefone"]:
        tel = a["telefone"] if a["telefone"].startswith("55") else "55" + a["telefone"]
        msg = f"Olá, {a['paciente'].split()[0]}! Segue o link para preencher sua documentação do atendimento: {novo_link['url']}\nO link vale até {novo_link['expira']}."
        wa = f"https://wa.me/{tel}?text={quote(msg)}"
    arquivos = q("SELECT COUNT(*) AS n FROM arquivos WHERE atendimento_id=?", (aid,))[0]["n"] if g.user["papel"] != "assistente" else 0
    return render_template("atendimentos/detalhe.html", a=a, docs=docs, links=links, agora=agora, novo_link=novo_link, wa=wa,
                           n_arquivos=arquivos, validade=current_app.config["LINK_VALIDADE_HORAS"],
                           link_remoto=current_app.config.get("LINK_REMOTO", True))


@bp.route("/<int:aid>/editar", methods=["POST"])
@login_required("profissional")
def editar(aid):
    a = _atendimento(aid)
    data = request.form.get("data_atendimento", a["data_atendimento"])
    try:
        datetime.strptime(data, "%Y-%m-%d")
    except ValueError:
        flash("Data inválida.", "erro")
        return redirect(url_for("atendimentos.detalhe", aid=aid))
    obs = request.form.get("observacoes", "").strip() or None
    evo = request.form.get("evolucao", "").strip() or None
    # Registro anterior preservado na auditoria (antes/depois)
    auditar("editar", "atendimentos", aid, {"antes": {"data": a["data_atendimento"], "observacoes": a["observacoes"], "evolucao": a["evolucao"]},
                                            "depois": {"data": data, "observacoes": obs, "evolucao": evo}})
    run("UPDATE atendimentos SET data_atendimento=?, observacoes=?, evolucao=?, atualizado_em=datetime('now') WHERE id=?", (data, obs, evo, aid))
    commit()
    flash("Atendimento atualizado.", "ok")
    return redirect(url_for("atendimentos.detalhe", aid=aid))


# ---------------------------------------------------------------- Links
@bp.route("/<int:aid>/links", methods=["POST"])
@login_required()
def criar_link(aid):
    a = _atendimento(aid)
    if not q1("SELECT 1 FROM atendimento_documentos WHERE atendimento_id=? AND status='pendente'", (aid,)):
        flash("Não há documentos pendentes para enviar.", "info")
        return redirect(url_for("atendimentos.detalhe", aid=aid))
    horas = request.form.get("horas", type=int) or current_app.config["LINK_VALIDADE_HORAS"]
    horas = min(max(horas, 1), 24 * 14)
    token = secrets.token_urlsafe(32)
    expira = (datetime.now(timezone.utc) + timedelta(hours=horas)).strftime("%Y-%m-%d %H:%M:%S")
    lid = run("INSERT INTO links_acesso (atendimento_id,token_hash,expira_em,criado_por) VALUES (?,?,?,?)",
              (aid, hashlib.sha256(token.encode()).hexdigest(), expira, g.user["id"]))
    auditar("criar_link", "links_acesso", lid, {"atendimento": aid, "expira_em": expira})
    commit()
    base = current_app.config.get("PUBLIC_BASE_URL") or request.host_url.rstrip("/")
    from . import _fmt_dt
    session["novo_link"] = {"url": f"{base}/p/{token}", "expira": _fmt_dt(expira)}
    return redirect(url_for("atendimentos.detalhe", aid=aid))


@bp.route("/<int:aid>/presencial", methods=["POST"])
@login_required()
def presencial(aid):
    """Assinatura com a paciente presente: abre a tela da paciente neste aparelho (link curto, 2 horas)."""
    _atendimento(aid)
    pend = q1("SELECT 1 FROM atendimento_documentos WHERE atendimento_id=? AND status='pendente'", (aid,))
    if not pend:
        flash("Não há documentos pendentes para a paciente.", "info")
        return redirect(url_for("atendimentos.detalhe", aid=aid))
    token = secrets.token_urlsafe(32)
    expira = (datetime.now(timezone.utc) + timedelta(hours=2)).strftime("%Y-%m-%d %H:%M:%S")
    lid = run("INSERT INTO links_acesso (atendimento_id,token_hash,expira_em,criado_por) VALUES (?,?,?,?)",
              (aid, hashlib.sha256(token.encode()).hexdigest(), expira, g.user["id"]))
    auditar("criar_link_presencial", "links_acesso", lid, {"atendimento": aid})
    commit()
    session["presencial_aid"] = aid
    did = request.form.get("doc", type=int)
    if did and q1("SELECT 1 FROM atendimento_documentos WHERE id=? AND atendimento_id=? AND tipo='termo' AND status='pendente'", (did, aid)):
        return redirect(url_for("publico.termo", token=token, did=did))
    return redirect(url_for("publico.inicio", token=token))


@bp.route("/<int:aid>/links/<int:lid>/revogar", methods=["POST"])
@login_required()
def revogar_link(aid, lid):
    q1("SELECT 1 FROM links_acesso WHERE id=? AND atendimento_id=?", (lid, aid)) or abort(404)
    run("UPDATE links_acesso SET revogado_em=datetime('now') WHERE id=? AND revogado_em IS NULL", (lid,))
    auditar("revogar_link", "links_acesso", lid)
    commit()
    flash("Link revogado. Ele não abre mais.", "ok")
    return redirect(url_for("atendimentos.detalhe", aid=aid))


# ---------------------------------------------------------------- Documentos
def _doc(aid, did):
    d = q1("SELECT d.*, COALESCE(m.nome, t.titulo) AS nome, t.tipo AS tipo_termo, COALESCE(fv.numero, tv.numero) AS versao, tv.conteudo AS termo_texto "
           "FROM atendimento_documentos d "
           "LEFT JOIN fichas_versao fv ON fv.id=d.ficha_versao_id LEFT JOIN fichas_modelo m ON m.id=fv.modelo_id "
           "LEFT JOIN termos_versao tv ON tv.id=d.termo_versao_id LEFT JOIN termos_modelo t ON t.id=tv.termo_id "
           "WHERE d.id=? AND d.atendimento_id=?", (did, aid))
    return d or abort(404)


@bp.route("/<int:aid>/documentos/<int:did>", methods=["GET", "POST"])
@login_required("profissional")
def documento(aid, did):
    a = _atendimento(aid)
    d = _doc(aid, did)
    campos = campos_da_versao(d["ficha_versao_id"]) if d["tipo"] == "ficha" else []
    if request.method == "POST":  # profissional preenche a ficha presencialmente
        if d["tipo"] != "ficha" or d["status"] != "pendente":
            abort(400, "Este documento não pode ser preenchido aqui.")
        valores, erros = ler_respostas(campos, request.form)
        if erros:
            for e in erros:
                flash(e, "erro")
            return render_template("atendimentos/documento.html", a=a, d=d, campos=campos, respostas=request.form, ass=None, adendos=[],
                                   integro=None, editavel=True, formatar=formatar_valor, opcoes=opcoes_do_campo), 400
        concluir_ficha(d, valores, "profissional")
        commit()
        flash("Ficha salva.", "ok")
        return redirect(url_for("atendimentos.documento", aid=aid, did=did))
    respostas = respostas_do_documento(did) if d["tipo"] == "ficha" else {}
    ass = q1("SELECT * FROM assinaturas WHERE documento_id=?", (did,))
    adendos = q("SELECT ad.*, u.nome AS autor FROM adendos ad LEFT JOIN usuarios u ON u.id=ad.usuario_id WHERE documento_id=? ORDER BY ad.id", (did,))
    return render_template("atendimentos/documento.html", a=a, d=d, campos=campos, respostas=respostas, ass=ass, adendos=adendos,
                           integro=verificar_integridade(did), editavel=(d["tipo"] == "ficha" and d["status"] == "pendente"),
                           formatar=formatar_valor, opcoes=opcoes_do_campo)


@bp.route("/<int:aid>/documentos/<int:did>/conferir", methods=["POST"])
@login_required("profissional")
def conferir(aid, did):
    d = _doc(aid, did)
    if d["status"] not in ("preenchido", "assinado"):
        flash("Este documento ainda não foi preenchido ou assinado.", "erro")
    elif verificar_integridade(did) is False:
        flash("Atenção: a integridade do documento não confere. Ele não pode ser conferido.", "erro")
    else:
        run("UPDATE atendimento_documentos SET status='conferido' WHERE id=?", (did,))
        auditar("conferir", "atendimento_documentos", did)
        commit()
        flash("Documento conferido.", "ok")
    return redirect(url_for("atendimentos.documento", aid=aid, did=did))


@bp.route("/<int:aid>/documentos/<int:did>/adendo", methods=["POST"])
@login_required("profissional")
def adendo(aid, did):
    d = _doc(aid, did)
    texto = request.form.get("texto", "").strip()
    if d["status"] == "pendente":
        flash("Adendos servem para documentos já concluídos.", "erro")
    elif len(texto) < 3:
        flash("Escreva o adendo.", "erro")
    else:
        i = run("INSERT INTO adendos (documento_id,texto,usuario_id) VALUES (?,?,?)", (did, texto, g.user["id"]))
        auditar("adendo", "atendimento_documentos", did, {"adendo": i})
        commit()
        flash("Adendo registrado. O documento original não foi alterado.", "ok")
    return redirect(url_for("atendimentos.documento", aid=aid, did=did))

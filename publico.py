"""Página do paciente: acesso por link individual, sem conta. Só enxerga os documentos do atendimento do link."""
import hashlib
from datetime import datetime, timezone

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for

from .db import commit, q, q1, run
from .documentos import (TEXTO_ACEITE, assinar_termo, campos_da_versao, concluir_ficha, ler_respostas,
                         opcoes_do_campo, validar_assinatura)

bp = Blueprint("publico", __name__, url_prefix="/p")


def _link_valido(token):
    h = hashlib.sha256(token.encode()).hexdigest()
    l = q1("SELECT * FROM links_acesso WHERE token_hash=?", (h,))
    agora = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    if not l or l["revogado_em"] or l["expira_em"] < agora:
        return None
    run("UPDATE links_acesso SET ultimo_acesso=? WHERE id=?", (agora, l["id"]))
    commit()
    return l


def _invalido():
    return render_template("publico/invalido.html"), 404


def _doc(link, did):
    d = q1("SELECT d.*, a.paciente_id, COALESCE(m.nome, t.titulo) AS nome, t.tipo AS tipo_termo, tv.conteudo AS termo_texto "
           "FROM atendimento_documentos d JOIN atendimentos a ON a.id=d.atendimento_id "
           "LEFT JOIN fichas_versao fv ON fv.id=d.ficha_versao_id LEFT JOIN fichas_modelo m ON m.id=fv.modelo_id "
           "LEFT JOIN termos_versao tv ON tv.id=d.termo_versao_id LEFT JOIN termos_modelo t ON t.id=tv.termo_id "
           "WHERE d.id=? AND d.atendimento_id=?", (did, link["atendimento_id"]))
    return d or abort(404)


@bp.route("/<token>")
def inicio(token):
    link = _link_valido(token)
    if not link:
        return _invalido()
    a = q1("SELECT a.*, p.nome AS paciente, pr.nome AS procedimento FROM atendimentos a "
           "JOIN pacientes p ON p.id=a.paciente_id JOIN procedimentos pr ON pr.id=a.procedimento_id WHERE a.id=?", (link["atendimento_id"],))
    docs = q("SELECT d.*, COALESCE(m.nome, t.titulo) AS nome, t.tipo AS tipo_termo FROM atendimento_documentos d "
             "LEFT JOIN fichas_versao fv ON fv.id=d.ficha_versao_id LEFT JOIN fichas_modelo m ON m.id=fv.modelo_id "
             "LEFT JOIN termos_versao tv ON tv.id=d.termo_versao_id LEFT JOIN termos_modelo t ON t.id=tv.termo_id "
             "WHERE d.atendimento_id=? ORDER BY d.tipo, t.tipo, d.id", (a["id"],))
    pendentes = sum(1 for d in docs if d["status"] == "pendente")
    return render_template("publico/inicio.html", token=token, a=a, docs=docs, pendentes=pendentes, primeiro_nome=a["paciente"].split()[0])


@bp.route("/<token>/ficha/<int:did>", methods=["GET", "POST"])
def ficha(token, did):
    link = _link_valido(token)
    if not link:
        return _invalido()
    d = _doc(link, did)
    if d["tipo"] != "ficha":
        abort(404)
    if d["status"] != "pendente":
        flash("Esta ficha já foi enviada. Obrigado!", "info")
        return redirect(url_for("publico.inicio", token=token))
    campos = campos_da_versao(d["ficha_versao_id"])
    if request.method == "POST":
        valores, erros = ler_respostas(campos, request.form)
        if erros:
            for e in erros:
                flash(e, "erro")
            return render_template("publico/ficha.html", token=token, d=d, campos=campos, respostas=request.form, opcoes=opcoes_do_campo), 400
        concluir_ficha(d, valores, "link")
        commit()
        flash("Ficha enviada. Obrigado!", "ok")
        return redirect(url_for("publico.inicio", token=token))
    return render_template("publico/ficha.html", token=token, d=d, campos=campos, respostas={}, opcoes=opcoes_do_campo)


@bp.route("/<token>/termo/<int:did>", methods=["GET", "POST"])
def termo(token, did):
    link = _link_valido(token)
    if not link:
        return _invalido()
    d = _doc(link, did)
    if d["tipo"] != "termo":
        abort(404)
    if d["status"] != "pendente":
        flash("Este termo já foi assinado. Obrigado!", "info")
        return redirect(url_for("publico.inicio", token=token))
    if request.method == "POST":
        erros, nome, cpf, aceite = validar_assinatura(d["tipo_termo"], request.form)
        if erros:
            for e in erros:
                flash(e, "erro")
            return render_template("publico/termo.html", token=token, d=d, f=request.form, texto_aceite=TEXTO_ACEITE[d["tipo_termo"]]), 400
        assinar_termo(d, d["tipo_termo"], nome, cpf, aceite, request.form.get("desenho"), request.remote_addr,
                      request.headers.get("User-Agent"), link["id"])
        commit()
        flash("Documento assinado. Obrigado!", "ok")
        return redirect(url_for("publico.inicio", token=token))
    return render_template("publico/termo.html", token=token, d=d, f={}, texto_aceite=TEXTO_ACEITE[d["tipo_termo"]])

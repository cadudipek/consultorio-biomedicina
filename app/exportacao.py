import os
import csv
import io
import json
import zipfile
from xml.sax.saxutils import escape

from flask import Blueprint, abort, current_app, flash, g, redirect, render_template, request, send_file, url_for
from reportlab.lib import colors

from . import _fmt_cpf, _fmt_dt
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import HRFlowable, Image as RLImage, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from .backup import fazer_backup, listar_backups
from .db import auditar, commit, q, q1
from .documentos import campos_da_versao, formatar_valor, respostas_do_documento, verificar_integridade
from .seguranca import login_required

bp = Blueprint("exportacao", __name__)

ROTULO_STATUS = {"preenchido": "Concluído, aguardando conferência", "assinado": "Assinado, aguardando conferência", "conferido": "Conferido pela profissional"}


# ------------------------------------------------------------------ PDF
def _estilos():
    s = getSampleStyleSheet()
    return {
        "h1": ParagraphStyle("h1", parent=s["Heading1"], fontSize=16, textColor=colors.HexColor("#16584a"), spaceAfter=6),
        "h2": ParagraphStyle("h2", parent=s["Heading2"], fontSize=12.5, textColor=colors.HexColor("#16584a"), spaceBefore=10, spaceAfter=4),
        "p": ParagraphStyle("p", parent=s["BodyText"], fontSize=10, leading=14),
        "pq": ParagraphStyle("pq", parent=s["BodyText"], fontSize=8.5, leading=11, textColor=colors.HexColor("#555555")),
        "mono": ParagraphStyle("mono", parent=s["BodyText"], fontName="Courier", fontSize=7.5, leading=9.5, wordWrap="CJK"),
    }


def _txt(v):
    return escape(v or "—").replace("\n", "<br/>")


def _rodape(canvas, doc):
    canvas.saveState()
    canvas.setFont("Helvetica", 8)
    canvas.setFillColor(colors.HexColor("#666666"))
    canvas.drawString(2 * cm, 1.2 * cm, "Documento gerado pelo sistema de Gestão de Pacientes")
    canvas.drawRightString(A4[0] - 2 * cm, 1.2 * cm, f"Página {doc.page}")
    canvas.restoreState()


def _bloco_documento(d, a, st):
    itens = []
    versao = d["versao"]
    itens.append(Paragraph(f"{_txt(d['nome'])} <font size=9 color='#666666'>(versão {versao})</font>", st["h2"]))
    itens.append(Paragraph(f"Situação: {ROTULO_STATUS.get(d['status'], d['status'])}", st["pq"]))
    if d["tipo"] == "ficha":
        resp = respostas_do_documento(d["id"])
        linhas = [[Paragraph(f"<b>{_txt(c['rotulo'])}</b>", st["p"]), Paragraph(_txt(formatar_valor(c, resp.get(c["id"]))), st["p"])]
                  for c in campos_da_versao(d["ficha_versao_id"])]
        if linhas:
            t = Table(linhas, colWidths=[6 * cm, 11 * cm])
            t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LINEBELOW", (0, 0), (-1, -1), 0.3, colors.HexColor("#cccccc"))]))
            itens.append(t)
    else:
        itens.append(Paragraph(_txt(d["termo_texto"]), st["p"]))
        ass = q1("SELECT * FROM assinaturas WHERE documento_id=?", (d["id"],))
        if ass:
            itens.append(Spacer(1, 6))
            itens.append(Paragraph("<b>Assinatura eletrônica</b>", st["p"]))
            itens.append(Paragraph(
                f"Resultado: <b>{'ACEITE / AUTORIZAÇÃO' if ass['aceite'] else 'NÃO AUTORIZOU'}</b><br/>"
                f"Signatário: {_txt(ass['nome_signatario'])} — CPF {_fmt_cpf(ass['cpf_signatario'])}<br/>"
                f"Data e hora: {_fmt_dt(ass['assinado_em'], '%d/%m/%Y %H:%M:%S')} (horário de Brasília; registro UTC {ass['assinado_em']}) · IP: {_txt(ass['ip'])}<br/>"
                f"Declaração aceita: “{_txt(ass['texto_aceite'])}”", st["p"]))
            if ass["desenho_png"]:
                try:
                    itens.append(RLImage(io.BytesIO(ass["desenho_png"]), width=5 * cm, height=2 * cm, kind="proportional"))
                except Exception:
                    pass
    adendos = q("SELECT ad.*, u.nome AS autor FROM adendos ad LEFT JOIN usuarios u ON u.id=ad.usuario_id WHERE documento_id=? ORDER BY ad.id", (d["id"],))
    for ad in adendos:
        itens.append(Paragraph(f"<b>Adendo</b> ({_fmt_dt(ad['criado_em'])}, {_txt(ad['autor'])}): {_txt(ad['texto'])}", st["pq"]))
    integro = verificar_integridade(d["id"])
    sel = "íntegro (confere com o registrado)" if integro else "ALTERADO após a conclusão"
    itens.append(Paragraph(f"Integridade: <b>{sel}</b><br/>SHA-256: {d['hash_documento']}", st["mono"]))
    return itens


def gerar_pdf(aid, did=None):
    a = q1("SELECT a.*, p.nome AS paciente, p.cpf, p.data_nascimento, pr.nome AS procedimento FROM atendimentos a "
           "JOIN pacientes p ON p.id=a.paciente_id JOIN procedimentos pr ON pr.id=a.procedimento_id WHERE a.id=?", (aid,)) or abort(404)
    sql = ("SELECT d.*, COALESCE(m.nome, t.titulo) AS nome, COALESCE(fv.numero, tv.numero) AS versao, tv.conteudo AS termo_texto "
           "FROM atendimento_documentos d LEFT JOIN fichas_versao fv ON fv.id=d.ficha_versao_id LEFT JOIN fichas_modelo m ON m.id=fv.modelo_id "
           "LEFT JOIN termos_versao tv ON tv.id=d.termo_versao_id LEFT JOIN termos_modelo t ON t.id=tv.termo_id "
           "WHERE d.atendimento_id=? AND d.status!='pendente'")
    args = [aid]
    if did:
        sql += " AND d.id=?"
        args.append(did)
    docs = q(sql + " ORDER BY d.tipo, d.id", args)
    if not docs:
        abort(404, "Não há documentos concluídos para exportar.")
    st = _estilos()
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=2 * cm, rightMargin=2 * cm, topMargin=1.8 * cm, bottomMargin=2 * cm,
                            title=f"Documentação - {a['paciente']}", author="Gestão de Pacientes")
    el = [Paragraph("Documentação do atendimento", st["h1"]),
          Paragraph(f"<b>Paciente:</b> {_txt(a['paciente'])}<br/><b>Procedimento:</b> {_txt(a['procedimento'])}<br/>"
                    f"<b>Data do atendimento:</b> {a['data_atendimento'][8:10]}/{a['data_atendimento'][5:7]}/{a['data_atendimento'][:4]}", st["p"]),
          HRFlowable(width="100%", color=colors.HexColor("#cccccc"), spaceBefore=6)]
    for d in docs:
        el.extend(_bloco_documento(d, a, st))
    doc.build(el, onFirstPage=_rodape, onLaterPages=_rodape)
    buf.seek(0)
    return buf, a


@bp.route("/atendimentos/<int:aid>/pdf")
@login_required("profissional")
def pdf_atendimento(aid):
    buf, a = gerar_pdf(aid)
    auditar("exportar_pdf", "atendimentos", aid)
    commit()
    return send_file(buf, mimetype="application/pdf", as_attachment=True, download_name=f"atendimento-{aid}.pdf")


@bp.route("/atendimentos/<int:aid>/documentos/<int:did>/pdf")
@login_required("profissional")
def pdf_documento(aid, did):
    buf, a = gerar_pdf(aid, did)
    auditar("exportar_pdf", "atendimento_documentos", did)
    commit()
    return send_file(buf, mimetype="application/pdf", as_attachment=True, download_name=f"documento-{did}.pdf")


# ------------------------------------------------------------------ Dados
def _celula(v):
    """Evita injeção de fórmula ao abrir o CSV no Excel."""
    if v is None:
        return ""
    v = str(v)
    return "'" + v if v[:1] in ("=", "+", "-", "@", "\t", "\r") else v


def _csv(cabecalho, linhas):
    out = io.StringIO()
    w = csv.writer(out, delimiter=";")
    w.writerow(cabecalho)
    for l in linhas:
        w.writerow([_celula(x) for x in l])
    return "﻿" + out.getvalue()  # BOM para o Excel abrir com acentos


def montar_zip():
    arquivos = {}
    arquivos["pacientes.csv"] = _csv(
        ["id", "nome", "cpf", "data_nascimento", "telefone", "email", "observacoes", "ativo", "criado_em"],
        [[r[k] for k in ("id", "nome", "cpf", "data_nascimento", "telefone", "email", "observacoes", "ativo", "criado_em")] for r in q("SELECT * FROM pacientes ORDER BY nome_busca")])
    arquivos["atendimentos.csv"] = _csv(
        ["id", "paciente", "procedimento", "data", "observacoes", "evolucao"],
        [[r["id"], r["paciente"], r["procedimento"], r["data_atendimento"], r["observacoes"], r["evolucao"]] for r in q(
            "SELECT a.*, p.nome AS paciente, pr.nome AS procedimento FROM atendimentos a JOIN pacientes p ON p.id=a.paciente_id "
            "JOIN procedimentos pr ON pr.id=a.procedimento_id ORDER BY a.data_atendimento, a.id")])
    arquivos["documentos.csv"] = _csv(
        ["atendimento", "documento", "tipo", "versao", "status", "concluido_em_utc", "sha256"],
        [[r["atendimento_id"], r["nome"], r["tipo"], r["versao"], r["status"], r["concluido_em"], r["hash_documento"]] for r in q(
            "SELECT d.*, COALESCE(m.nome,t.titulo) AS nome, COALESCE(fv.numero,tv.numero) AS versao FROM atendimento_documentos d "
            "LEFT JOIN fichas_versao fv ON fv.id=d.ficha_versao_id LEFT JOIN fichas_modelo m ON m.id=fv.modelo_id "
            "LEFT JOIN termos_versao tv ON tv.id=d.termo_versao_id LEFT JOIN termos_modelo t ON t.id=tv.termo_id ORDER BY d.atendimento_id, d.id")])
    linhas = []
    for d in q("SELECT d.id, d.atendimento_id, d.ficha_versao_id, m.nome FROM atendimento_documentos d "
               "JOIN fichas_versao fv ON fv.id=d.ficha_versao_id JOIN fichas_modelo m ON m.id=fv.modelo_id WHERE d.status!='pendente' ORDER BY d.id"):
        resp = respostas_do_documento(d["id"])
        for c in campos_da_versao(d["ficha_versao_id"]):
            linhas.append([d["atendimento_id"], d["nome"], c["rotulo"], formatar_valor(c, resp.get(c["id"]))])
    arquivos["respostas_das_fichas.csv"] = _csv(["atendimento", "ficha", "pergunta", "resposta"], linhas)
    arquivos["assinaturas.csv"] = _csv(
        ["documento", "signatario", "cpf", "aceite", "assinado_em_utc", "ip", "sha256"],
        [[r["documento_id"], r["nome_signatario"], r["cpf_signatario"], r["aceite"], r["assinado_em"], r["ip"], r["hash_documento"]] for r in q("SELECT * FROM assinaturas ORDER BY id")])
    arquivos["arquivos_fotos.csv"] = _csv(
        ["id", "paciente_id", "atendimento_id", "data", "momento", "descricao", "sha256"],
        [[r["id"], r["paciente_id"], r["atendimento_id"], r["data_registro"], r["momento"], r["descricao"], r["sha256"]] for r in q("SELECT * FROM arquivos ORDER BY id")])
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for nome, conteudo in arquivos.items():
            z.writestr(nome, conteudo)
        z.writestr("LEIAME.txt", "Exportação de dados (CSV, separador ponto e vírgula, UTF-8).\nContém dados pessoais e de saúde: guarde com segurança e não envie por canais abertos.\n")
    buf.seek(0)
    return buf


@bp.route("/exportacao/")
@login_required("profissional")
def pagina():
    return render_template("exportacao.html", backups=listar_backups(current_app) if g.user["papel"] == "admin" else [])


@bp.route("/exportacao/dados.zip", methods=["POST"])
@login_required("profissional")
def dados_zip():
    buf = montar_zip()
    auditar("exportar_dados", "sistema", None)
    commit()
    return send_file(buf, mimetype="application/zip", as_attachment=True, download_name="dados-consultorio.zip")


@bp.route("/exportacao/restaurar", methods=["POST"])
@login_required("admin")
def restaurar_backup():
    from flask import session
    from .backup import BackupInvalido, restaurar
    f = request.files.get("arquivo")
    if not f or not f.filename:
        flash("Escolha o arquivo de backup.", "erro")
        return redirect(url_for("exportacao.pagina"))
    if request.form.get("confirmo") != "1":
        flash("Marque a confirmação: os dados atuais serão substituídos pelos do backup.", "erro")
        return redirect(url_for("exportacao.pagina"))
    try:
        restaurar(current_app, f)
    except BackupInvalido as e:
        flash(str(e), "erro")
        return redirect(url_for("exportacao.pagina"))
    session.clear()
    flash("Backup restaurado. Entre com o e-mail e a senha que valiam quando o backup foi feito.", "ok")
    return redirect(url_for("auth.login"))


@bp.route("/exportacao/backup", methods=["POST"])
@login_required("admin")
def backup():
    caminho = fazer_backup(current_app)
    auditar("backup", "sistema", None, {"arquivo": os.path.basename(caminho)})
    commit()
    if request.form.get("baixar"):  # cópia para o pendrive / outro local escolhido pela usuária
        return send_file(caminho, mimetype="application/gzip", as_attachment=True, download_name=os.path.basename(caminho))
    flash("Backup criado na pasta de backups do sistema.", "ok")
    return redirect(url_for("exportacao.pagina"))

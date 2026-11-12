from flask import Blueprint, flash, g, redirect, render_template, url_for

from . import inicial
from .db import commit, q, q1
from .seguranca import login_required

bp = Blueprint("painel", __name__)


@bp.route("/")
@login_required()
def inicio():
    # Atendimentos com pelo menos um documento ainda não concluído
    aguardando = q(
        "SELECT a.id, a.data_atendimento, p.id AS paciente_id, p.nome AS paciente, pr.nome AS procedimento, "
        " SUM(CASE WHEN d.tipo='ficha' AND d.status='pendente' THEN 1 ELSE 0 END) AS fichas_pend, "
        " SUM(CASE WHEN d.tipo='termo' AND d.status='pendente' THEN 1 ELSE 0 END) AS termos_pend, "
        " SUM(CASE WHEN d.status IN ('preenchido','assinado') THEN 1 ELSE 0 END) AS a_conferir, "
        " COUNT(d.id) AS total "
        "FROM atendimentos a "
        "JOIN pacientes p ON p.id=a.paciente_id "
        "JOIN procedimentos pr ON pr.id=a.procedimento_id "
        "JOIN atendimento_documentos d ON d.atendimento_id=a.id "
        "GROUP BY a.id HAVING SUM(CASE WHEN d.status='conferido' THEN 0 ELSE 1 END) > 0 "
        "ORDER BY a.data_atendimento DESC, a.id DESC")
    concluidos = q(
        "SELECT a.id, a.data_atendimento, p.id AS paciente_id, p.nome AS paciente, pr.nome AS procedimento "
        "FROM atendimentos a JOIN pacientes p ON p.id=a.paciente_id "
        "JOIN procedimentos pr ON pr.id=a.procedimento_id "
        "WHERE EXISTS (SELECT 1 FROM atendimento_documentos d WHERE d.atendimento_id=a.id) "
        "AND NOT EXISTS (SELECT 1 FROM atendimento_documentos d WHERE d.atendimento_id=a.id AND d.status!='conferido') "
        "ORDER BY a.data_atendimento DESC, a.id DESC LIMIT 8")
    n = {k: q1(f"SELECT COUNT(*) AS n FROM {t} WHERE {w}")["n"] for k, t, w in (
        ("termos", "termos_modelo", "ativo=1"), ("fichas", "fichas_modelo", "ativo=1"),
        ("procs", "procedimentos", "ativo=1"), ("pacs", "pacientes", "1=1"), ("atends", "atendimentos", "1=1"))}
    passos = [
        ("Escolher a ficha de anamnese e os termos", n["fichas"] > 0 and n["termos"] > 0, "/modelos/"),
        ("Cadastrar seus procedimentos", n["procs"] > 0, "/procedimentos/"),
        ("Cadastrar a primeira paciente", n["pacs"] > 0, "/pacientes/novo"),
        ("Abrir o primeiro atendimento", n["atends"] > 0, "/pacientes/"),
    ]
    ultimo_backup = q1("SELECT MAX(criado_em) AS m FROM auditoria WHERE acao='backup'")["m"]
    lembrar_backup = n["pacs"] > 0 and (not ultimo_backup or
                                        q1("SELECT julianday('now') - julianday(?) > 7 AS v", (ultimo_backup,))["v"])
    nomes = [p for p in g.user["nome"].split() if not p.endswith(".")]
    return render_template("painel.html", primeiro_nome=nomes[0] if nomes else "", aguardando=aguardando, concluidos=concluidos, passos=passos,
                           mostrar_passos=not all(p[1] for p in passos), sem_modelos=n["fichas"] == 0 and n["termos"] == 0,
                           lembrar_backup=lembrar_backup, ultimo_backup=ultimo_backup)


@bp.route("/modelos-iniciais", methods=["POST"])
@login_required("profissional")
def modelos_iniciais():
    if inicial.ja_existe():
        flash("Os modelos iniciais já foram criados.", "info")
    else:
        inicial.criar()
        commit()
        flash("Pronto! Criamos uma ficha de anamnese, os dois termos e um procedimento de exemplo. "
              "Revise os textos em “Fichas e termos” antes de usar com pacientes.", "ok")
    return redirect(url_for("painel.inicio"))

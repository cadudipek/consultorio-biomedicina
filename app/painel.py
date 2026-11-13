from flask import Blueprint, render_template

from .db import q
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
    return render_template("painel.html", aguardando=aguardando, concluidos=concluidos)

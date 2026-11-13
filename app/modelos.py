import json

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for

from .db import auditar, commit, q, q1, run
from .documentos import TIPOS, campos_da_versao, opcoes_do_campo, sha256
from .seguranca import login_required

bp = Blueprint("modelos", __name__, url_prefix="/modelos")


@bp.route("/")
@login_required("profissional")
def lista():
    fichas = q(
        "SELECT m.*, (SELECT MAX(numero) FROM fichas_versao v WHERE v.modelo_id=m.id) AS versao, "
        "(SELECT COUNT(*) FROM procedimento_fichas pf WHERE pf.ficha_modelo_id=m.id) AS n_proc "
        "FROM fichas_modelo m ORDER BY m.ativo DESC, m.nome")
    termos = q(
        "SELECT t.*, (SELECT MAX(numero) FROM termos_versao v WHERE v.termo_id=t.id) AS versao, "
        "(SELECT COUNT(*) FROM procedimento_termos pt WHERE pt.termo_id=t.id) AS n_proc "
        "FROM termos_modelo t ORDER BY t.ativo DESC, t.tipo, t.titulo")
    return render_template("modelos/lista.html", fichas=fichas, termos=termos)


# ------------------------------------------------------------------ Fichas
def _versao_atual(modelo_id):
    return q1("SELECT * FROM fichas_versao WHERE modelo_id=? ORDER BY numero DESC LIMIT 1", (modelo_id,))


def _versao_em_uso(versao_id):
    return q1("SELECT 1 FROM atendimento_documentos WHERE ficha_versao_id=?", (versao_id,)) is not None


@bp.route("/fichas/novo", methods=["GET", "POST"])
@login_required("profissional")
def ficha_nova():
    if request.method == "POST":
        nome = request.form.get("nome", "").strip()
        if len(nome) < 2:
            flash("Informe o nome da ficha.", "erro")
        elif q1("SELECT 1 FROM fichas_modelo WHERE lower(nome)=lower(?)", (nome,)):
            flash("Já existe uma ficha com esse nome.", "erro")
        else:
            mid = run("INSERT INTO fichas_modelo (nome,descricao) VALUES (?,?)", (nome, request.form.get("descricao", "").strip() or None))
            run("INSERT INTO fichas_versao (modelo_id,numero) VALUES (?,1)", (mid,))
            auditar("criar", "fichas_modelo", mid, {"nome": nome})
            commit()
            return redirect(url_for("modelos.ficha_editar", mid=mid))
    return render_template("modelos/ficha_nova.html")


def _ler_campos_form(form):
    campos, erros = [], []
    for i in range(int(form.get("n_campos", "0") or 0)):
        rotulo = form.get(f"c{i}_rotulo", "").strip()
        if not rotulo:
            continue
        tipo = form.get(f"c{i}_tipo", "texto")
        if tipo not in TIPOS:
            erros.append(f"“{rotulo}”: tipo inválido.")
            continue
        opcoes = None
        if tipo in ("escolha_unica", "multipla_escolha"):
            lista = [o.strip() for o in form.get(f"c{i}_opcoes", "").splitlines() if o.strip()]
            if len(lista) < 2:
                erros.append(f"“{rotulo}”: informe pelo menos 2 opções (uma por linha).")
            opcoes = json.dumps(lista, ensure_ascii=False)
        campos.append({"rotulo": rotulo, "tipo": tipo, "obrigatorio": 1 if form.get(f"c{i}_obrig") else 0,
                       "opcoes": opcoes, "ajuda": form.get(f"c{i}_ajuda", "").strip() or None})
    if not campos:
        erros.append("A ficha precisa ter pelo menos uma pergunta.")
    return campos, erros


@bp.route("/fichas/<int:mid>", methods=["GET", "POST"])
@login_required("profissional")
def ficha_editar(mid):
    modelo = q1("SELECT * FROM fichas_modelo WHERE id=?", (mid,)) or abort(404)
    versao = _versao_atual(mid)
    em_uso = _versao_em_uso(versao["id"])
    if request.method == "POST":
        campos, erros = _ler_campos_form(request.form)
        nome = request.form.get("nome", "").strip()
        if len(nome) < 2:
            erros.append("Informe o nome da ficha.")
        if q1("SELECT 1 FROM fichas_modelo WHERE lower(nome)=lower(?) AND id!=?", (nome, mid)):
            erros.append("Já existe uma ficha com esse nome.")
        if erros:
            for e in erros:
                flash(e, "erro")
        else:
            run("UPDATE fichas_modelo SET nome=?, descricao=? WHERE id=?", (nome, request.form.get("descricao", "").strip() or None, mid))
            if em_uso:  # versão já usada em atendimentos: nunca altera, cria a próxima
                vid = run("INSERT INTO fichas_versao (modelo_id,numero) VALUES (?,?)", (mid, versao["numero"] + 1))
                numero = versao["numero"] + 1
            else:
                vid, numero = versao["id"], versao["numero"]
                run("DELETE FROM ficha_campos WHERE versao_id=?", (vid,))
            for ordem, c in enumerate(campos, 1):
                run("INSERT INTO ficha_campos (versao_id,ordem,rotulo,tipo,obrigatorio,opcoes,ajuda) VALUES (?,?,?,?,?,?,?)",
                    (vid, ordem, c["rotulo"], c["tipo"], c["obrigatorio"], c["opcoes"], c["ajuda"]))
            auditar("editar", "fichas_modelo", mid, {"versao": numero, "campos": [c["rotulo"] for c in campos], "nova_versao": bool(em_uso)})
            commit()
            flash(f"Ficha salva (versão {numero})." + (" Atendimentos anteriores continuam com a versão que usaram." if em_uso else ""), "ok")
            return redirect(url_for("modelos.ficha_editar", mid=mid))
        versao_campos = [
            {"rotulo": request.form.get(f"c{i}_rotulo", ""), "tipo": request.form.get(f"c{i}_tipo", "texto"),
             "obrigatorio": 1 if request.form.get(f"c{i}_obrig") else 0, "opcoes": request.form.get(f"c{i}_opcoes", ""), "ajuda": request.form.get(f"c{i}_ajuda", "")}
            for i in range(int(request.form.get("n_campos", "0") or 0))]
    else:
        versao_campos = []
        for c in campos_da_versao(versao["id"]):
            versao_campos.append({"rotulo": c["rotulo"], "tipo": c["tipo"], "obrigatorio": c["obrigatorio"],
                                  "opcoes": "\n".join(opcoes_do_campo(c)), "ajuda": c["ajuda"] or ""})
    return render_template("modelos/ficha_editar.html", modelo=modelo, versao=versao, campos=versao_campos, tipos=TIPOS, em_uso=em_uso)


@bp.route("/fichas/<int:mid>/alternar", methods=["POST"])
@login_required("profissional")
def ficha_alternar(mid):
    q1("SELECT 1 FROM fichas_modelo WHERE id=?", (mid,)) or abort(404)
    run("UPDATE fichas_modelo SET ativo=1-ativo WHERE id=?", (mid,))
    auditar("alternar_ativo", "fichas_modelo", mid)
    commit()
    return redirect(url_for("modelos.lista"))


# ------------------------------------------------------------------ Termos
@bp.route("/termos/novo", methods=["GET", "POST"])
@login_required("profissional")
def termo_novo():
    if request.method == "POST":
        titulo = request.form.get("titulo", "").strip()
        tipo = request.form.get("tipo")
        conteudo = request.form.get("conteudo", "").strip()
        if len(titulo) < 2 or tipo not in ("consentimento", "imagem") or len(conteudo) < 20:
            flash("Informe título, tipo e o texto do termo (mínimo de 20 caracteres).", "erro")
        elif q1("SELECT 1 FROM termos_modelo WHERE lower(titulo)=lower(?)", (titulo,)):
            flash("Já existe um termo com esse título.", "erro")
        else:
            tid = run("INSERT INTO termos_modelo (titulo,tipo) VALUES (?,?)", (titulo, tipo))
            run("INSERT INTO termos_versao (termo_id,numero,conteudo,hash_conteudo) VALUES (?,1,?,?)", (tid, conteudo, sha256(conteudo)))
            auditar("criar", "termos_modelo", tid, {"titulo": titulo, "tipo": tipo})
            commit()
            flash("Termo cadastrado.", "ok")
            return redirect(url_for("modelos.termo_editar", tid=tid))
    return render_template("modelos/termo_novo.html", f=request.form)


@bp.route("/termos/<int:tid>", methods=["GET", "POST"])
@login_required("profissional")
def termo_editar(tid):
    termo = q1("SELECT * FROM termos_modelo WHERE id=?", (tid,)) or abort(404)
    atual = q1("SELECT * FROM termos_versao WHERE termo_id=? ORDER BY numero DESC LIMIT 1", (tid,))
    if request.method == "POST":
        titulo = request.form.get("titulo", "").strip()
        conteudo = request.form.get("conteudo", "").strip()
        if len(titulo) < 2 or len(conteudo) < 20:
            flash("Informe título e texto (mínimo de 20 caracteres).", "erro")
        elif q1("SELECT 1 FROM termos_modelo WHERE lower(titulo)=lower(?) AND id!=?", (titulo, tid)):
            flash("Já existe um termo com esse título.", "erro")
        else:
            run("UPDATE termos_modelo SET titulo=? WHERE id=?", (titulo, tid))
            if conteudo != atual["conteudo"]:
                n = atual["numero"] + 1
                run("INSERT INTO termos_versao (termo_id,numero,conteudo,hash_conteudo) VALUES (?,?,?,?)", (tid, n, conteudo, sha256(conteudo)))
                auditar("nova_versao", "termos_modelo", tid, {"versao": n})
                flash(f"Nova versão criada (v{n}). Atendimentos anteriores continuam com a versão que usaram.", "ok")
            else:
                flash("Título atualizado. O texto não mudou, então não foi criada nova versão.", "ok")
            commit()
            return redirect(url_for("modelos.termo_editar", tid=tid))
    versoes = q("SELECT v.*, (SELECT COUNT(*) FROM atendimento_documentos d WHERE d.termo_versao_id=v.id) AS usos "
                "FROM termos_versao v WHERE termo_id=? ORDER BY numero DESC", (tid,))
    return render_template("modelos/termo_editar.html", termo=termo, atual=atual, versoes=versoes)


@bp.route("/termos/<int:tid>/alternar", methods=["POST"])
@login_required("profissional")
def termo_alternar(tid):
    q1("SELECT 1 FROM termos_modelo WHERE id=?", (tid,)) or abort(404)
    run("UPDATE termos_modelo SET ativo=1-ativo WHERE id=?", (tid,))
    auditar("alternar_ativo", "termos_modelo", tid)
    commit()
    return redirect(url_for("modelos.lista"))


# ------------------------------------------------------------------ Impressão em branco
@bp.route("/fichas/<int:mid>/imprimir")
@login_required("profissional")
def ficha_imprimir(mid):
    modelo = q1("SELECT * FROM fichas_modelo WHERE id=?", (mid,)) or abort(404)
    versao = _versao_atual(mid)
    campos = [{**dict(c), "lista": opcoes_do_campo(c)} for c in campos_da_versao(versao["id"])]
    auditar("imprimir_em_branco", "fichas_modelo", mid, {"versao": versao["numero"]})
    commit()
    return render_template("modelos/imprimir_ficha.html", modelo=modelo, versao=versao, campos=campos)


@bp.route("/termos/<int:tid>/imprimir")
@login_required("profissional")
def termo_imprimir(tid):
    termo = q1("SELECT * FROM termos_modelo WHERE id=?", (tid,)) or abort(404)
    versao = q1("SELECT * FROM termos_versao WHERE termo_id=? ORDER BY numero DESC LIMIT 1", (tid,))
    auditar("imprimir_em_branco", "termos_modelo", tid, {"versao": versao["numero"]})
    commit()
    return render_template("modelos/imprimir_termo.html", termo=termo, versao=versao)

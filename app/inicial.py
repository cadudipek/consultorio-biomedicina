"""Modelos iniciais (não são de demonstração): ponto de partida para a profissional revisar e adaptar."""
import json

from . import db as d
from .documentos import sha256

AVISO = "[MODELO INICIAL — revise e ajuste este texto com a sua orientação profissional/jurídica antes de usar.]"

CONSENT = f"""TERMO DE CONSENTIMENTO LIVRE E ESCLARECIDO

{AVISO}

Eu, paciente identificado(a) abaixo, declaro que fui informado(a) de forma clara sobre o procedimento que será realizado, seus objetivos, as etapas, os cuidados necessários antes e depois, os resultados esperados (que podem variar de pessoa para pessoa) e as possíveis reações e intercorrências.

Declaro que informei com sinceridade meu histórico de saúde, alergias e medicamentos em uso, e que pude tirar todas as minhas dúvidas.

Autorizo a realização do procedimento e sei que posso desistir a qualquer momento antes do seu início."""

IMAGEM = f"""AUTORIZAÇÃO DE USO DE IMAGEM

{AVISO}

Este documento é separado do consentimento do procedimento. A minha escolha aqui não interfere no atendimento.

Fotos de antes e depois são feitas para acompanhar a evolução do tratamento e ficam guardadas no meu prontuário. Abaixo eu escolho se AUTORIZO ou NÃO AUTORIZO que essas imagens também sejam usadas, sem identificação do meu nome, em materiais de divulgação da profissional (redes sociais, apresentações)."""

CAMPOS = [
    ("Qual o motivo da sua consulta?", "texto_longo", 1, None),
    ("Possui alguma alergia (medicamentos, cosméticos, alimentos)?", "sim_nao", 1, None, "Quais?"),
    ("Usa algum medicamento atualmente?", "sim_nao", 1, None, "Quais?"),
    ("Está grávida ou amamentando?", "sim_nao", 1, None),
    ("Possui alguma destas condições?", "multipla_escolha", 0,
     ["Diabetes", "Hipertensão", "Problemas de cicatrização", "Herpes", "Doença autoimune", "Nenhuma"]),
    ("Já fez algum procedimento estético antes? Qual?", "texto", 0, None),
]


def ja_existe():
    return d.q1("SELECT 1 FROM fichas_modelo WHERE nome=?", ("Anamnese geral (modelo inicial)",)) is not None


def criar():
    mid = d.run("INSERT INTO fichas_modelo (nome,descricao,demonstracao) VALUES (?,?,0)",
                ("Anamnese geral (modelo inicial)", "Perguntas básicas de saúde. Edite à vontade."))
    vid = d.run("INSERT INTO fichas_versao (modelo_id,numero) VALUES (?,1)", (mid,))
    for i, (rot, tipo, ob, ops, *det) in enumerate(CAMPOS, 1):
        d.run("INSERT INTO ficha_campos (versao_id,ordem,rotulo,tipo,obrigatorio,opcoes,detalhe) VALUES (?,?,?,?,?,?,?)",
              (vid, i, rot, tipo, ob, json.dumps(ops, ensure_ascii=False) if ops else None, det[0] if det else None))
    t1 = d.run("INSERT INTO termos_modelo (titulo,tipo,demonstracao) VALUES (?,?,0)", ("Termo de consentimento (modelo inicial)", "consentimento"))
    d.run("INSERT INTO termos_versao (termo_id,numero,conteudo,hash_conteudo) VALUES (?,1,?,?)", (t1, CONSENT, sha256(CONSENT)))
    t2 = d.run("INSERT INTO termos_modelo (titulo,tipo,demonstracao) VALUES (?,?,0)", ("Autorização de uso de imagem (modelo inicial)", "imagem"))
    d.run("INSERT INTO termos_versao (termo_id,numero,conteudo,hash_conteudo) VALUES (?,1,?,?)", (t2, IMAGEM, sha256(IMAGEM)))
    pid = d.run("INSERT INTO procedimentos (nome,descricao,demonstracao) VALUES (?,?,0)",
                ("Atendimento padrão (modelo inicial)", "Renomeie para o seu procedimento ou crie outros."))
    d.run("INSERT INTO procedimento_fichas VALUES (?,?)", (pid, mid))
    d.run("INSERT INTO procedimento_termos VALUES (?,?)", (pid, t1))
    d.run("INSERT INTO procedimento_termos VALUES (?,?)", (pid, t2))
    d.auditar("criar_modelos_iniciais", "sistema", None)

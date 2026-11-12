-- =====================================================================
-- Modelo relacional: Sistema de Documentação e Histórico de Pacientes
-- Consultório de Biomedicina (Contagem/MG)
-- SGBD: SQLite 3 (migração para PostgreSQL descrita em docs/ARQUITETURA.md)
-- =====================================================================
PRAGMA foreign_keys = ON;

-- ---------- Acesso ----------
CREATE TABLE IF NOT EXISTS usuarios (
    id            INTEGER PRIMARY KEY,
    nome          TEXT    NOT NULL,
    email         TEXT    NOT NULL UNIQUE,
    senha_hash    TEXT    NOT NULL,
    papel         TEXT    NOT NULL CHECK (papel IN ('admin','profissional','assistente')),
    ativo         INTEGER NOT NULL DEFAULT 1 CHECK (ativo IN (0,1)),
    tentativas    INTEGER NOT NULL DEFAULT 0,
    bloqueado_ate TEXT,
    criado_em     TEXT    NOT NULL DEFAULT (datetime('now'))
);

-- ---------- Pacientes ----------
CREATE TABLE IF NOT EXISTS pacientes (
    id               INTEGER PRIMARY KEY,
    nome             TEXT NOT NULL,
    nome_busca       TEXT NOT NULL,              -- minúsculo e sem acento, para busca
    cpf              TEXT UNIQUE,                -- só dígitos; opcional
    data_nascimento  TEXT,
    telefone         TEXT,
    email            TEXT,
    observacoes      TEXT,
    ativo            INTEGER NOT NULL DEFAULT 1 CHECK (ativo IN (0,1)),
    criado_em        TEXT NOT NULL DEFAULT (datetime('now')),
    atualizado_em    TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS ix_pacientes_busca ON pacientes (nome_busca);

-- ---------- Procedimentos ----------
CREATE TABLE IF NOT EXISTS procedimentos (
    id         INTEGER PRIMARY KEY,
    nome       TEXT NOT NULL UNIQUE,
    descricao  TEXT,
    ativo      INTEGER NOT NULL DEFAULT 1 CHECK (ativo IN (0,1)),
    demonstracao INTEGER NOT NULL DEFAULT 0
);

-- ---------- Modelos de ficha (anamnese) com versões ----------
CREATE TABLE IF NOT EXISTS fichas_modelo (
    id         INTEGER PRIMARY KEY,
    nome       TEXT NOT NULL UNIQUE,
    descricao  TEXT,
    ativo      INTEGER NOT NULL DEFAULT 1 CHECK (ativo IN (0,1)),
    demonstracao INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS fichas_versao (
    id         INTEGER PRIMARY KEY,
    modelo_id  INTEGER NOT NULL REFERENCES fichas_modelo(id),
    numero     INTEGER NOT NULL,
    publicada  INTEGER NOT NULL DEFAULT 0 CHECK (publicada IN (0,1)),
    criado_em  TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (modelo_id, numero)
);
CREATE TABLE IF NOT EXISTS ficha_campos (
    id          INTEGER PRIMARY KEY,
    versao_id   INTEGER NOT NULL REFERENCES fichas_versao(id) ON DELETE CASCADE,
    ordem       INTEGER NOT NULL,
    rotulo      TEXT NOT NULL,
    tipo        TEXT NOT NULL CHECK (tipo IN
                ('texto','texto_longo','numero','data','sim_nao','escolha_unica','multipla_escolha')),
    obrigatorio INTEGER NOT NULL DEFAULT 0 CHECK (obrigatorio IN (0,1)),
    opcoes      TEXT,             -- JSON: lista de opções (escolha_unica / multipla_escolha)
    ajuda       TEXT
);
CREATE INDEX IF NOT EXISTS ix_campos_versao ON ficha_campos (versao_id, ordem);

-- ---------- Termos com versões imutáveis ----------
CREATE TABLE IF NOT EXISTS termos_modelo (
    id         INTEGER PRIMARY KEY,
    titulo     TEXT NOT NULL UNIQUE,
    tipo       TEXT NOT NULL CHECK (tipo IN ('consentimento','imagem')),
    ativo      INTEGER NOT NULL DEFAULT 1 CHECK (ativo IN (0,1)),
    demonstracao INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS termos_versao (
    id            INTEGER PRIMARY KEY,
    termo_id      INTEGER NOT NULL REFERENCES termos_modelo(id),
    numero        INTEGER NOT NULL,
    conteudo      TEXT NOT NULL,
    hash_conteudo TEXT NOT NULL,        -- SHA-256 do texto
    criado_em     TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (termo_id, numero)
);

-- ---------- Procedimento x documentos (N:N) ----------
CREATE TABLE IF NOT EXISTS procedimento_fichas (
    procedimento_id INTEGER NOT NULL REFERENCES procedimentos(id) ON DELETE CASCADE,
    ficha_modelo_id INTEGER NOT NULL REFERENCES fichas_modelo(id),
    PRIMARY KEY (procedimento_id, ficha_modelo_id)
);
CREATE TABLE IF NOT EXISTS procedimento_termos (
    procedimento_id INTEGER NOT NULL REFERENCES procedimentos(id) ON DELETE CASCADE,
    termo_id        INTEGER NOT NULL REFERENCES termos_modelo(id),
    PRIMARY KEY (procedimento_id, termo_id)
);

-- ---------- Atendimentos ----------
CREATE TABLE IF NOT EXISTS atendimentos (
    id               INTEGER PRIMARY KEY,
    paciente_id      INTEGER NOT NULL REFERENCES pacientes(id),
    procedimento_id  INTEGER NOT NULL REFERENCES procedimentos(id),
    data_atendimento TEXT NOT NULL,
    observacoes      TEXT,
    evolucao         TEXT,
    criado_por       INTEGER REFERENCES usuarios(id),
    criado_em        TEXT NOT NULL DEFAULT (datetime('now')),
    atualizado_em    TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS ix_atend_paciente ON atendimentos (paciente_id, data_atendimento DESC);
CREATE INDEX IF NOT EXISTS ix_atend_proc ON atendimentos (procedimento_id);

-- Cada documento exigido em um atendimento fixa a VERSÃO usada.
CREATE TABLE IF NOT EXISTS atendimento_documentos (
    id               INTEGER PRIMARY KEY,
    atendimento_id   INTEGER NOT NULL REFERENCES atendimentos(id) ON DELETE CASCADE,
    tipo             TEXT NOT NULL CHECK (tipo IN ('ficha','termo')),
    ficha_versao_id  INTEGER REFERENCES fichas_versao(id),
    termo_versao_id  INTEGER REFERENCES termos_versao(id),
    status           TEXT NOT NULL DEFAULT 'pendente'
                     CHECK (status IN ('pendente','preenchido','assinado','conferido')),
    concluido_em     TEXT,
    hash_documento   TEXT,        -- SHA-256 do conteúdo no momento da conclusão
    CHECK ((tipo='ficha' AND ficha_versao_id IS NOT NULL AND termo_versao_id IS NULL) OR
           (tipo='termo' AND termo_versao_id IS NOT NULL AND ficha_versao_id IS NULL))
);
CREATE INDEX IF NOT EXISTS ix_docs_atend ON atendimento_documentos (atendimento_id);

CREATE TABLE IF NOT EXISTS respostas (
    id           INTEGER PRIMARY KEY,
    documento_id INTEGER NOT NULL REFERENCES atendimento_documentos(id) ON DELETE CASCADE,
    campo_id     INTEGER NOT NULL REFERENCES ficha_campos(id),
    valor        TEXT,
    UNIQUE (documento_id, campo_id)
);

-- ---------- Links de preenchimento remoto ----------
CREATE TABLE IF NOT EXISTS links_acesso (
    id             INTEGER PRIMARY KEY,
    atendimento_id INTEGER NOT NULL REFERENCES atendimentos(id) ON DELETE CASCADE,
    token_hash     TEXT NOT NULL UNIQUE,   -- só o hash fica no banco, nunca o token
    expira_em      TEXT NOT NULL,
    revogado_em    TEXT,
    criado_por     INTEGER REFERENCES usuarios(id),
    criado_em      TEXT NOT NULL DEFAULT (datetime('now')),
    ultimo_acesso  TEXT
);

-- ---------- Assinatura eletrônica (aceite) ----------
CREATE TABLE IF NOT EXISTS assinaturas (
    id               INTEGER PRIMARY KEY,
    documento_id     INTEGER NOT NULL UNIQUE REFERENCES atendimento_documentos(id),
    nome_signatario  TEXT NOT NULL,
    cpf_signatario   TEXT,
    texto_aceite     TEXT NOT NULL,      -- frase exata aceita pelo signatário
    aceite           INTEGER NOT NULL CHECK (aceite IN (0,1)),   -- 1 = aceitou/autorizou, 0 = recusou
    assinado_em      TEXT NOT NULL,      -- UTC
    ip               TEXT,
    user_agent       TEXT,
    hash_documento   TEXT NOT NULL,
    via_link_id      INTEGER REFERENCES links_acesso(id),
    desenho_png      BLOB                -- complemento visual; NÃO é a garantia
);

-- ---------- Fotos e arquivos (guardados fora da pasta pública) ----------
CREATE TABLE IF NOT EXISTS arquivos (
    id             INTEGER PRIMARY KEY,
    paciente_id    INTEGER NOT NULL REFERENCES pacientes(id),
    atendimento_id INTEGER REFERENCES atendimentos(id),
    nome_original  TEXT NOT NULL,
    caminho        TEXT NOT NULL UNIQUE,
    mime           TEXT NOT NULL,
    tamanho        INTEGER NOT NULL,
    sha256         TEXT NOT NULL,
    descricao      TEXT,
    data_registro  TEXT NOT NULL,
    momento        TEXT NOT NULL DEFAULT 'outro' CHECK (momento IN ('antes','depois','outro')),
    criado_por     INTEGER REFERENCES usuarios(id),
    criado_em      TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS ix_arq_paciente ON arquivos (paciente_id);

-- ---------- Registro de alterações ----------
CREATE TABLE IF NOT EXISTS auditoria (
    id         INTEGER PRIMARY KEY,
    usuario_id INTEGER REFERENCES usuarios(id),
    acao       TEXT NOT NULL,
    entidade   TEXT NOT NULL,
    entidade_id INTEGER,
    detalhes   TEXT,                  -- JSON com antes/depois
    ip         TEXT,
    criado_em  TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS ix_aud_entidade ON auditoria (entidade, entidade_id);

-- Auditoria é append-only: ninguém altera nem apaga registros.
CREATE TRIGGER IF NOT EXISTS trg_auditoria_no_update BEFORE UPDATE ON auditoria
BEGIN SELECT RAISE(ABORT, 'auditoria é somente de inserção'); END;
CREATE TRIGGER IF NOT EXISTS trg_auditoria_no_delete BEFORE DELETE ON auditoria
BEGIN SELECT RAISE(ABORT, 'auditoria é somente de inserção'); END;

-- Termos publicados são imutáveis (nova edição = nova versão).
CREATE TRIGGER IF NOT EXISTS trg_termo_versao_imutavel BEFORE UPDATE ON termos_versao
BEGIN SELECT RAISE(ABORT, 'versão de termo é imutável'); END;

-- Respostas de documentos concluídos não podem ser alteradas.
CREATE TRIGGER IF NOT EXISTS trg_resposta_travada_upd BEFORE UPDATE ON respostas
WHEN (SELECT status FROM atendimento_documentos WHERE id = OLD.documento_id) IN ('preenchido','assinado','conferido')
BEGIN SELECT RAISE(ABORT, 'documento concluído: respostas travadas'); END;
CREATE TRIGGER IF NOT EXISTS trg_resposta_travada_del BEFORE DELETE ON respostas
WHEN (SELECT status FROM atendimento_documentos WHERE id = OLD.documento_id) IN ('preenchido','assinado','conferido')
BEGIN SELECT RAISE(ABORT, 'documento concluído: respostas travadas'); END;

-- Assinaturas também são imutáveis.
CREATE TRIGGER IF NOT EXISTS trg_assinatura_no_update BEFORE UPDATE ON assinaturas
BEGIN SELECT RAISE(ABORT, 'assinatura é imutável'); END;
CREATE TRIGGER IF NOT EXISTS trg_assinatura_no_delete BEFORE DELETE ON assinaturas
BEGIN SELECT RAISE(ABORT, 'assinatura é imutável'); END;

-- ---------- Adendos: correções posteriores sem sobrescrever o original ----------
CREATE TABLE IF NOT EXISTS adendos (
    id           INTEGER PRIMARY KEY,
    documento_id INTEGER NOT NULL REFERENCES atendimento_documentos(id),
    texto        TEXT NOT NULL,
    usuario_id   INTEGER REFERENCES usuarios(id),
    criado_em    TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TRIGGER IF NOT EXISTS trg_adendo_no_update BEFORE UPDATE ON adendos
BEGIN SELECT RAISE(ABORT, 'adendo é imutável'); END;
CREATE TRIGGER IF NOT EXISTS trg_adendo_no_delete BEFORE DELETE ON adendos
BEGIN SELECT RAISE(ABORT, 'adendo é imutável'); END;

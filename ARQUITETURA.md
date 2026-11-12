# Arquitetura e modelo de dados

Sistema de documentação e histórico de pacientes para consultório de biomedicina.
Dados de demonstração são sempre fictícios e identificados como tal.

## 1. Escolha técnica e justificativa

A proposta inicial previa Google Sheets + Apps Script. Com os requisitos levantados
com a profissional, essa base deixou de servir. O ajuste é permitido pela
observação da Validação da Proposta.

| Requisito | Planilha + Apps Script | Escolhido: Flask + SQLite |
|---|---|---|
| Banco relacional com chaves e restrições | Não (abas soltas) | Sim (`schema.sql`) |
| Arquivos privados por paciente | Pastas do Drive, difícil de controlar | Pasta fora do alcance web, servida só após login |
| Link individual com prazo, sem conta | Limitado | Token com hash e validade |
| Histórico imutável / auditoria | Planilha é editável | Gatilhos (triggers) impedem alteração |
| Assinatura com hash e data/hora | Frágil | Hash SHA-256 e carimbo UTC |
| PDF e exportação | Complexo | `reportlab` e CSV/JSON |

Por que SQLite e não PostgreSQL: um único consultório (poucas centenas de
pacientes, um ou dois usuários) não precisa de servidor de banco. Backup é copiar
um arquivo, não há custo e o risco de configuração é menor. O SQL é padrão
(chaves estrangeiras, CHECK, índices e triggers) e migra para PostgreSQL com
pequenos ajustes (`AUTOINCREMENT` por `GENERATED ... AS IDENTITY`, `datetime('now')`
por `now()`). Essa migração só se justifica se o uso crescer.

Por que sem ORM: o SQL aparece de forma explícita e fica fácil de apresentar e
avaliar na disciplina.

## 2. Camadas

```
Navegador (PC / tablet / celular)  — HTML responsivo, sem framework JS
        │  HTTPS
Flask (blueprints)
  auth · pacientes · procedimentos · modelos · atendimentos · publico · arquivos · painel · exportacao
        │
SQLite (instance/consultorio.db)  +  pasta privada instance/uploads/
```

Blueprints = módulos. Cada um tem suas rotas e templates. O módulo `publico`
(página do paciente) é o único acessível sem login, e só por token.

## 3. Segurança

- Senhas com hash (Werkzeug/scrypt). Bloqueio temporário após 5 tentativas.
- Sessão com cookie `HttpOnly`, `SameSite=Lax` e `Secure` em produção.
- Proteção CSRF em todo formulário POST.
- Permissões por papel: `admin` (tudo, usuários), `profissional` (tudo clínico),
  `assistente` (cadastro e envio de links; sem excluir nem ver fotos clínicas).
- Link do paciente: token aleatório de 256 bits. O banco guarda só o SHA-256.
  Dá acesso apenas aos documentos daquele atendimento, tem prazo e pode ser revogado.
- Arquivos em `instance/uploads/`, nunca em `static/`. Entrega só por rota autenticada,
  com validação do tipo real da imagem (Pillow) e nome aleatório.
- Auditoria append-only (triggers) com usuário, ação, antes/depois e IP.
- LGPD: dados de saúde são sensíveis. Coletar o mínimo, termo de uso de imagem
  separado, acesso restrito, nada de dados reais no GitHub (`.gitignore`).

## 4. Assinatura eletrônica: o que é e o que não é

O fluxo registra: identificação do signatário (nome e CPF informados), aceite
explícito (caixa marcada com frase registrada), data/hora UTC, IP, navegador e
**hash SHA-256 do documento** (texto do termo na versão usada + respostas). Qualquer
alteração posterior muda o hash e fica detectável. O desenho da assinatura é
opcional e só complementa.

Isso configura assinatura eletrônica simples (Lei 14.063/2020), com evidências
fortes de autoria e integridade. **Não é assinatura qualificada ICP-Brasil.** Se a
profissional ou a vigilância sanitária exigir validade qualificada, é preciso
integrar um provedor de certificado digital. Isso fica registrado como limitação
conhecida.

## 5. Preservação de histórico

- Termo: cada edição cria nova versão; o atendimento aponta para a versão usada.
- Ficha: mesma regra (`fichas_versao` + `ficha_campos`). Campos de versão já
  usada não são editados; o editor cria versão nova.
- Respostas concluídas ficam travadas por trigger. Correção posterior é feita como
  adendo registrado na auditoria, sem sobrescrever a resposta original.
- Atendimentos antigos nunca são sobrescritos. Cada um é um registro próprio.

## 6. Modelo (DER textual)

```
usuarios
pacientes 1──N atendimentos N──1 procedimentos
procedimentos N──N fichas_modelo 1──N fichas_versao 1──N ficha_campos
procedimentos N──N termos_modelo 1──N termos_versao
atendimentos 1──N atendimento_documentos ──(ficha_versao | termo_versao)
atendimento_documentos 1──N respostas N──1 ficha_campos
atendimento_documentos 1──1 assinaturas
atendimentos 1──N links_acesso
pacientes 1──N arquivos N──0..1 atendimentos
auditoria (registra todas as entidades)
```

SQL completo em `schema.sql`. Normalização: 3FN. A exceção intencional é
`pacientes.nome_busca`, derivado do nome e usado para busca sem acento.

## 7. Custos e dependências

| Item | Custo |
|---|---|
| Software (Flask, Pillow, reportlab, SQLite) | R$ 0 (código aberto) |
| Hospedagem (VPS pequena ou PaaS com disco persistente) | cerca de R$ 25–50/mês (estimativa; conferir preço atual) |
| Domínio (opcional) | cerca de R$ 40/ano |
| HTTPS | gratuito (Let's Encrypt, ou incluído no PaaS) |
| Backup | script incluso; cópia externa pode ser gratuita (Drive) |

Para a demonstração acadêmica, roda no notebook (`flask run`) sem custo.
Para uso real no consultório é obrigatório HTTPS e disco persistente.

## 8. Escopo da v1

Inclui: pacientes, procedimentos, fichas, termos, atendimentos, link remoto,
assinatura eletrônica, fotos, pendências, exportação.
Fora: financeiro, estoque, IA. **Agendamento:** a confirmar com a profissional.

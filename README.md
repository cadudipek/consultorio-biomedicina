# Gestão de Pacientes — Consultório de Biomedicina

Sistema web (computador, tablet e celular) para substituir fichas em papel: cadastro de pacientes,
procedimentos, anamneses configuráveis, termos versionados, link de preenchimento remoto com prazo,
assinatura eletrônica com verificação de integridade, fotos antes/depois, pendências e exportação em PDF/CSV.

Projeto da Atividade Extensionista II (Tecnologia em Banco de Dados). **Todos os dados de exemplo são fictícios.**
Arquitetura, justificativa técnica e custos: `docs/ARQUITETURA.md`. Modelo do banco: `schema.sql`.

## Instalação no Windows (recomendada)

Baixe o instalador `Consultorio-Setup-*.exe` na página **Releases** deste repositório, execute e siga o assistente.
O aplicativo abre em janela própria; no primeiro uso pede nome, e-mail e senha. Os dados ficam em
`%LOCALAPPDATA%\Consultorio` e **não** são apagados ao desinstalar. Para testar com dados fictícios, use o
atalho "Consultório (demonstração)". O instalador é gerado automaticamente por `.github/workflows/instalador.yml`.

## Rodar no seu computador (demonstração)

```bash
python3 -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
flask --app app seed            # cria banco, usuários e dados FICTÍCIOS
flask --app app run
```
Abra http://127.0.0.1:5000. Acesso de demonstração (só para o banco de demonstração):
`demo@exemplo.test` / `demonstracao-123` (administradora) e `assistente@exemplo.test` / mesma senha.

## Uso real no consultório (sem dados de exemplo)

```bash
flask --app app init-db
flask --app app criar-usuario --papel admin     # pergunta nome, e-mail e senha (mín. 10 caracteres)
```
Não rode `seed` no banco real (ele se recusa se já houver usuários).

## Implantação (HTTPS obrigatório com dados reais)

O link do paciente e os dados de saúde exigem conexão segura. Duas opções:

**A) Servidor (VPS) com Linux**
1. Instale Python 3.11+, `nginx` e `certbot` (HTTPS gratuito, Let's Encrypt).
2. Copie o projeto, crie o `.venv` e instale `requirements.txt`.
3. Variáveis de ambiente: `COOKIE_SECURE=1`, `TRUST_PROXY=1`, `PUBLIC_BASE_URL=https://seu-dominio`.
4. Rode com `gunicorn -w 2 -b 127.0.0.1:8000 "app:create_app()"` (como serviço `systemd`) e aponte o nginx para ele.
5. No nginx, `client_max_body_size 12m;`.
6. A pasta `instance/` (banco e fotos) precisa ficar em disco persistente e **fora** de qualquer pasta pública.

**B) Plataforma gerenciada (PaaS)**: use as mesmas variáveis e o comando do gunicorn, e monte um
disco persistente em `instance/`. Sem disco persistente os dados se perdem a cada deploy.

### Backup
- `flask --app app backup` (ou botão em “Exportar”, perfil admin): gera `instance/backups/backup-AAAAMMDD-HHMMSS.tar.gz` com banco e fotos (mantém os 14 mais recentes).
- Agende diariamente (`cron`: `0 2 * * * cd /caminho && .venv/bin/flask --app app backup`) e copie para outro local.
- **Teste a restauração**: extraia o `.tar.gz`, coloque `consultorio.db` e `uploads/` em `instance/`.

## Perfis de acesso
| Perfil | Pode |
|---|---|
| admin | tudo, inclusive usuários e backup |
| profissional | tudo clínico: fichas, termos, fotos, conferência, PDF, exportação |
| assistente | cadastrar pacientes, abrir atendimentos e gerar links. Não vê conteúdo clínico, fotos nem modelos |

## Assinatura eletrônica: o que o sistema garante
Registra nome e CPF do signatário, aceite explícito (texto exato), data/hora UTC, IP, navegador e SHA-256 do
documento (texto do termo na versão usada + respostas). Alterações posteriores são detectadas. O desenho é só complemento.
É assinatura eletrônica **simples**; não é ICP-Brasil. Se a profissional precisar de validade qualificada, é preciso integrar
certificado digital.

## Testes automatizados
```bash
python -m pytest tests -q        # 43 testes
```
Cobrem login e bloqueio, permissões, CSRF, CPF duplicado, versionamento de fichas e termos, fluxo do paciente por link,
link expirado/revogado, isolamento entre atendimentos, travas do banco, detecção de adulteração, upload seguro, PDF, ZIP, backup e seed.

## Roteiro de testes manual (com a profissional)
1. Entrar com `demo@exemplo.test`. Ver o painel de pendências.
2. **Pacientes**: cadastrar “Teste Fictício”; buscar por “teste” (sem acento) e filtrar por procedimento.
3. **Fichas e termos**: criar ficha com 1 pergunta de cada tipo; cadastrar um termo de consentimento e um de imagem.
4. **Procedimentos**: associar ficha e termos a um procedimento.
5. **Atendimento**: no perfil do paciente, “Abrir atendimento”.
6. **Link**: “Gerar link individual” e abrir o link em outro navegador/celular (sem login). Preencher a ficha (testar campo obrigatório vazio) e assinar os termos (testar sem marcar a confirmação). Recusar a autorização de imagem em um teste.
7. Voltar como profissional: abrir cada documento, conferir a integridade e marcar “conferido”. Registrar um adendo.
8. **Fotos**: enviar duas fotos (antes/depois) e usar “Comparar”.
9. **Link**: revogar e confirmar que o link deixa de abrir.
10. **PDF**: “Baixar PDF” no atendimento. **Exportar**: baixar o ZIP de dados.
11. **Histórico**: editar o termo (cria nova versão) e confirmar que o atendimento antigo mantém a versão original.
12. Conferir que um assistente não vê fotos nem conteúdo clínico.

## Pendências a confirmar com a profissional
- Agendamento: entra na v1? (hoje fora do escopo.)
- Textos reais de termos e fichas (os atuais são EXEMPLO).
- Necessidade de assinatura qualificada (ICP-Brasil).
- Política de retenção/descarte de dados e fotos (LGPD).

## Limitações conhecidas
- Edição de uma ficha já usada cria nova versão; não há migração de respostas antigas (de propósito).
- Não há recuperação de senha por e-mail: o admin redefine criando novo acesso.
- SQLite atende um consultório; mais de 1–2 usuários simultâneos intensos pedem PostgreSQL.

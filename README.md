# SEC-MME - Analise de Dados SIA/DATASUS

Projeto de ETL e visualizacao analitica para dados ambulatoriais do SIA/DATASUS, com carga em PostgreSQL e relatorio Power BI versionado no repositorio.

## O que este projeto faz

- Baixa arquivos `PA` do SIA/DATASUS para a UF `PB`.
- Valida se o mes disponivel corresponde ao periodo esperado, hoje configurado como dois meses antes da data de execucao.
- Converte os dados brutos para Parquet.
- Seleciona, renomeia, filtra e tipa as colunas usadas na analise.
- Carrega a tabela fato `data_sus` no PostgreSQL.
- Evita duplicidade mensal verificando se o periodo ja existe no banco.
- Mantem um projeto Power BI conectado ao modelo relacional publicado no banco.

## Documentacao

A documentacao tecnica completa esta em [docs/DOCUMENTACAO_TECNICA.md](docs/DOCUMENTACAO_TECNICA.md).

Ela detalha a arquitetura, estrutura de pastas, fluxo ETL, configuracao de ambiente, tabelas, modelo Power BI e pontos de atencao.

## Observabilidade

O app usa OpenTelemetry para traces, métricas e logs correlacionados. Em
produção, o serviço deve ser identificado exatamente como `dsc-eq10` e envia
OTLP/HTTP para o coletor institucional:

```text
FastAPI (app/) -> OpenTelemetry SDK -> OTLP/HTTP -> coletor institucional
               -> Tempo / Prometheus / Loki -> Grafana
```

A aplicação em produção é o app FastAPI (`app/`, ver
[docs/claude-migration.md](docs/claude-migration.md)), que substituiu o
Streamlit em `https://eq10.dsc.rodrigor.com/`. `app/main.py` chama
`configure_telemetry()` (definido em `src/observability/telemetry.py`, reutilizado
sem alterações) no startup do processo (`_lifespan()`), e emite o span
`app.startup`. Os spans `auth.login` (`app/routes/auth.py`) e `audit.list`
(`app/routes/audit.py`) são instrumentados manualmente com
`src.observability.telemetry.span()`, usando somente os atributos de baixa
cardinalidade já permitidos pelo módulo (`SAFE_ATTRIBUTE_KEYS`) — nunca
e-mail, senha, SQL ou identificador de usuário.

Em 2026-07-29, `dsc-eq10` e os traces de startup, autenticação, auditoria e
saúde dos bancos foram confirmados no Grafana Tempo (então ainda pelo
Streamlit). A credencial Bearer permanece somente no `.env.prod` protegido.

Para demonstração independente, há também uma stack local Alloy, Tempo,
Prometheus e Grafana com dashboard provisionado. Consulte
[docs/OBSERVABILITY_OPENTELEMETRY_GRAFANA.md](docs/OBSERVABILITY_OPENTELEMETRY_GRAFANA.md).

## Liveness e readiness

`GET /healthcheck` (`app/routes/healthcheck.py`) sempre responde HTTP 200 e é
usado pelo Uptime Kuma e pelo `HEALTHCHECK` do `Dockerfile.fastapi` — verifica
os dois bancos (aplicação e analítico) mas nunca derruba o container por uma
falha transitória de um deles.

`GET /health` (mesmo arquivo) é a checagem de prontidão do banco principal:
executa `SELECT 1` via `app/database/connection.py` e retorna HTTP 200 com
`{"status":"healthy","database":"connected"}` ou HTTP 503 com
`{"status":"unhealthy","database":"unavailable"}`. O banco analítico, OpenTelemetry
e Umami não participam desse resultado — mesma separação liveness/readiness
documentada para o Streamlit, agora nos dois endpoints do FastAPI.

Arquitetura, timeouts e comandos de validação (documento original, escrito
para o Streamlit — o contrato de `/health` é idêntico no FastAPI):
[docs/READINESS.md](docs/READINESS.md).

## Analytics de uso

A aplicação FastAPI integra o Umami institucional para page views lógicas e
poucos eventos de uso, sem enviar e-mail, identificador de usuário, prompts,
respostas ou dados de saúde. `app/config/settings.py` lê e valida a
configuração (reaproveitando os validadores puros de
`src/analytics/umami.py`); `app/templates/sidebar.html` injeta o `<script>`
do Umami no `<head>` com `data-auto-track="false"` — page views são enviadas
explicitamente por página lógica, nunca automaticamente. Umami descreve
navegação e uso do produto; OpenTelemetry continua responsável por traces,
métricas técnicas, latência, erros e saúde dos bancos. A integração é
opcional e não afeta a disponibilidade da aplicação.

Configuração, catálogo de eventos, privacidade e validação (documento
original, escrito para o Streamlit — variáveis de ambiente e regras de
privacidade são as mesmas no FastAPI):
[docs/UMAMI_ANALYTICS.md](docs/UMAMI_ANALYTICS.md).

## Camada de IA

Este projeto possui uma camada experimental e isolada de analise estatistica com PandasAI. Ela e somente leitura, nao executa a ETL principal e trabalha com DataFrames controlados da view `vw_data_sus_ia`.

Veja detalhes em: [docs/IA_PANDASAI.md](docs/IA_PANDASAI.md)

Interface experimental: `streamlit run app_ai_chat.py`

## Log de Auditoria

O projeto possui um modulo de log de auditoria para registrar eventos de seguranca, autenticacao, administracao e uso do Chat IA sem expor senhas, tokens ou segredos.

O que e auditado:

- autenticacao: login, falha de login e logout;
- contas: criacao, desativacao, reativacao, troca de e-mail e redefinicao de senha;
- autorizacao/admin: acesso negado a area de auditoria, alteracao de papel e concessao/revogacao de permissao de auditoria;
- Chat IA: prompt enviado, prompt bloqueado pelo guardrail e erro seguro de processamento;
- sistema: falha resumida de conexao com banco ou envio de e-mail.

Onde fica armazenado:

- tabela de aplicacao `audit_log`;
- principais campos: `id`, `evento`, `status`, `user_id`, `user_email`, `prompt_text`, `detalhe`, `source`, `action`, `criado_em`.

Como foi implementado (aplicação em produção — FastAPI, `app/`):

- serviço dedicado em `app/service/audit_service.py`: constantes de evento (`EVENT_*`),
  inferência de status (`success`/`failure`/`blocked`/`info`), sanitização de texto
  (`sanitize_text()`, `sanitize_display_text()` — remove senha, token, connection string,
  URL sensível antes de gravar ou exibir) e `log_event_safely()`, chamada de forma segura
  e não bloqueante (nunca propaga exceção) a partir de `app/service/auth_service.py`
  (login, registro, troca de senha/e-mail, reset, desativação) e
  `app/service/user_management_service.py` (mudança de papel, concessão/revogação de
  acesso à auditoria);
- persistência em SQL puro (psycopg2, sem ORM) em `app/database/audit_db.py`
  (`insert_audit_log()`, `get_recent_audit_logs()`, `get_audit_logs_by_user()`);
- visualização administrativa em `app/routes/audit.py` (`GET /auditoria`) e
  `app/templates/auditoria.html` — filtros por tipo de evento, status, e-mail e período,
  cartões de resumo e modal de detalhe do evento; acesso controlado por
  `app/middleware/guards.py:require_audit_access()` e `app/auth/roles.py`.
- implementação legada (referência, não mais a aplicação em produção, mas mantida no
  repositório): `src/audit/audit_log_service.py`, `src/ui/admin_page.py`.

Como visualizar/usar (produção, FastAPI):

- acesse `https://eq10.dsc.rodrigor.com/auth/login` e entre com um usuário autorizado
  (`role` igual a `admin` ou `super_admin`, ou `can_view_audit=true`);
- acesse `https://eq10.dsc.rodrigor.com/auditoria` (link "Auditoria" na sidebar, visível
  apenas para quem tem permissão);
- usuários não autenticados ou sem permissão são redirecionados e não acessam a página.

Para rodar localmente: `uv run uvicorn app.main:app --reload --port 8811` (veja
[docs/claude-migration.md](docs/claude-migration.md) para variáveis de ambiente e o
layout Docker completo em `Dockerfile.fastapi`).

## Integracoes Externas

O projeto usa integracoes externas reais ou configuraveis, sempre por variaveis de ambiente e sem versionar credenciais.

### Chat IA / Provedor LLM

- Uso: responder perguntas analiticas controladas sobre a view somente leitura `vw_data_sus_ia`.
- Implementacao: `src/ai/pandasai_runner.py`, `src/ai/datasus_ai.py`, `src/ai/prompt_guard.py`, `src/ai/simple_stats_runner.py` (camada de IA legada, reaproveitada sem alteração — chamada por `app/service/chat_service.py:process_question()` a partir de `app/routes/chat.py`, `POST /chat/ask`).
- Provedores suportados/configuraveis: OpenAI, Gemini e OpenRouter via PandasAI/LiteLLM.
- Variaveis principais: `AI_USE_LLM`, `AI_LLM_PROVIDER`, `AI_LLM_MODEL`, `AI_LLM_API_KEY`, `OPENAI_API_KEY`, `GEMINI_API_KEY`, `OPENROUTER_API_KEY`.
- Modo seguro/local: `AI_USE_LLM=false` usa respostas estatisticas simples sem chamar API externa.

### E-mail SMTP

- Uso: envio de link para recuperação de senha (fluxo ativo no FastAPI). O legado
  Streamlit também usava para cadastro/verificação/troca de e-mail/reativação — esses
  fluxos ainda não foram portados para o FastAPI (ver
  [docs/claude-migration.md](docs/claude-migration.md), seção "Deferred").
- Implementacao: `app/service/email_service.py` (aplicação em produção — `EmailConfig`,
  `EmailService.send_password_reset_email()`), consumido por
  `app/service/auth_service.py:request_password_reset()`. Implementação legada de
  referência: `src/auth/email_service.py`, `src/auth/pending_registration_service.py`,
  `src/auth/password_reset_service.py`, `src/auth/email_change_service.py`,
  `src/auth/email_verification_service.py`, `src/auth/account_reactivation_service.py`.
- Variaveis principais: `EMAIL_ENABLED`, `EMAIL_PROVIDER`, `EMAIL_FROM`, `EMAIL_SMTP_HOST`, `EMAIL_SMTP_PORT`, `EMAIL_SMTP_USERNAME`, `EMAIL_SMTP_PASSWORD`, `EMAIL_USE_TLS`, `APP_PUBLIC_BASE_URL`.
- Padrao seguro: `EMAIL_ENABLED=false`, sem envio real (modo "fake" — loga a tentativa, não conecta a nenhum SMTP real).

### Google OAuth / OpenID Connect

- Uso: login/cadastro com Google quando habilitado.
- Implementacao: `src/auth/google_oauth_service.py`, com integracao de usuario em `src/auth/user_service.py` e callback tratado em `app_ai_chat.py`. **Ainda não portado para o FastAPI** — ver [docs/claude-migration.md](docs/claude-migration.md), seção "Deferred".
- Variaveis principais: `GOOGLE_OAUTH_ENABLED`, `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `GOOGLE_REDIRECT_URI`.
- O sistema usa `google_sub` como identificador estavel e exige e-mail verificado pelo Google.

### MinIO / Object Storage para logo

- Uso: exibir o logo institucional da aplicacao quando houver uma URL publica ou assinada.
- Implementacao: `app/config/settings.py:get_configured_logo_url()` (aplicação em
  produção — mesma lógica de resolução de URL, portada de `src/ui/styles.py`),
  renderizado em `app/templates/sidebar.html`. Implementação legada: `src/ui/styles.py`,
  `src/ui/sidebar.py`.
- Variavel preferida: `APP_LOGO_URL`.
- Fallback local versionado: `images/logo.png`.
- O bucket MinIO pode permanecer privado para upload/administracao; nesse caso use uma URL assinada ou uma rota publica controlada. Se a URL nao estiver publica/acessivel, o app usa `images/logo.png`. Credenciais MinIO nao devem ser expostas no app.

### OpenTelemetry — coletor institucional (Grafana)

- Uso: exportar traces, métricas e logs correlacionados para Grafana Tempo/Prometheus/Loki,
  identificando o serviço como `dsc-eq10`.
- Implementacao: `src/observability/telemetry.py` (SDK completo, reaproveitado sem
  alteração — `configure_telemetry()`, `span()`, `add_metric()`), inicializado em
  `app/main.py` (`_lifespan()`, no startup do processo FastAPI). Spans manuais em
  `app/routes/auth.py` (`auth.login`) e `app/routes/audit.py` (`audit.list`).
- Variaveis principais: `OTEL_ENABLED`, `OTEL_SERVICE_NAME`, `OTEL_EXPORTER_OTLP_ENDPOINT`,
  `OTEL_EXPORTER_OTLP_PROTOCOL`, `OTEL_EXPORTER_OTLP_HEADERS` (token Bearer — nunca
  commitado, vive somente em `.env.prod`).
- Padrao seguro: `OTEL_ENABLED=false` por padrão; falha do exportador nunca afeta a
  disponibilidade da aplicação. Detalhes completos em
  [docs/OBSERVABILITY_OPENTELEMETRY_GRAFANA.md](docs/OBSERVABILITY_OPENTELEMETRY_GRAFANA.md).

### Umami Analytics

- Uso: medir page views lógicas e eventos de uso (login, chat, auditoria) sem dados
  identificáveis.
- Implementacao: `app/config/settings.py` (leitura/validação da configuração, reaproveita
  os validadores puros de `src/analytics/umami.py`), `app/templates/sidebar.html`
  (injeção do `<script>` no `<head>`, `data-auto-track="false"`).
- Variaveis principais: `UMAMI_ENABLED`, `UMAMI_SCRIPT_URL`, `UMAMI_WEBSITE_ID`,
  `UMAMI_HOST_URL`, `UMAMI_ALLOWED_DOMAIN`.
- Padrao seguro: `UMAMI_ENABLED=false` por padrão; nenhuma credencial de painel é usada
  pelo tracker. Catálogo de páginas/eventos e regras de privacidade completas em
  [docs/UMAMI_ANALYTICS.md](docs/UMAMI_ANALYTICS.md).

## Cobertura de Testes

Dois relatórios distintos, um por stack (Streamlit legado e FastAPI em produção):

### FastAPI (`app/`) — aplicação em produção

Relatório HTML completo commitado em [`cobertura/backend/index.html`](cobertura/backend/index.html).

Comando usado para gerar o relatório:

```bash
uv run pytest tests/test_app_*.py --cov=app --cov-report=html --cov-report=term -q
cp -r htmlcov/* cobertura/backend/
```

Resultado atual: **93,64%** de cobertura total de linhas (`app/`), acima do mínimo de 85%
exigido — 214 testes, todos com banco de dados mockado (sem depender de Postgres real).
Suíte em `tests/test_app_*.py` (auth/sessão/papéis, guards, settings, os cinco serviços de
negócio, a camada `app/database/` inteira, e as rotas via `TestClient`).

### Streamlit (legado)

A cobertura da aplicação Streamlit legada esta registrada em `cobertura/coverage-report.txt`.

Comando usado para gerar o relatorio:

```powershell
python scripts/coverage_unittest.py --fail-under 85
```

Resultado atual do relatorio em `cobertura/coverage-report.txt`: **85,5%** de cobertura total de linhas.

## Execucao rapida

Requisitos principais:

- Python `>=3.10,<3.12`
- Gerenciador `uv` ou outro instalador compativel com `pyproject.toml`
- PostgreSQL acessivel
- Arquivo `.env` para execucao via Docker ou `config/.env` para execucao Python direta

Instale as dependencias:

```powershell
uv sync
```

Para Docker, configure `.env` na raiz do projeto:

```env
user=seu_usuario
password=sua_senha
host=seu_host
database=seu_banco
```

Execute o pipeline principal:

```powershell
uv run python main.py
```

Ou execute com Docker:

```powershell
docker compose run --rm etl
```

Para carregar dimensoes manualmente pelo script auxiliar:

```powershell
docker compose run --rm dimensoes
```

## Arquivos principais

- `main.py`: orquestra o ETL mensal.
- `Dockerfile`: imagem da aplicacao ETL.
- `docker-compose.yml`: comandos Docker para ETL e carga manual de dimensoes.
- `src/extract.py`: extrai dados do SIA/DATASUS.
- `src/transform.py`: transforma e filtra os dados.
- `src/load.py`: conecta no PostgreSQL, verifica duplicidade e carrega dados.
- `src/utils.py`: calcula o periodo-alvo.
- `constants/constants.py`: centraliza filtros, colunas e tipos.
- `send_archives.py`: script auxiliar para carga manual de dimensoes.
- `power bi/`: projeto Power BI com relatorio, modelo semantico e imagens.

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
Streamlit -> OpenTelemetry SDK -> OTLP/HTTP -> coletor institucional
          -> Tempo / Prometheus / Loki -> Grafana
```

Em 2026-07-29, `dsc-eq10` e os traces de startup, autenticação, auditoria e
saúde dos bancos foram confirmados no Grafana Tempo. A credencial Bearer
permanece somente no `.env.prod` protegido.

Para demonstração independente, há também uma stack local Alloy, Tempo,
Prometheus e Grafana com dashboard provisionado. Consulte
[docs/OBSERVABILITY_OPENTELEMETRY_GRAFANA.md](docs/OBSERVABILITY_OPENTELEMETRY_GRAFANA.md).

## Analytics de uso

O Streamlit integra o Umami institucional para page views logicas e poucos
eventos de uso, sem enviar e-mail, identificador de usuario, prompts, respostas
ou dados de saude. Umami descreve navegacao e uso do produto; OpenTelemetry
continua responsavel por traces, metricas tecnicas, latencia, erros e saude dos
bancos. A integracao e opcional e nao afeta a disponibilidade da aplicacao.

Configuracao, catalogo de eventos, privacidade e validacao:
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

Como foi implementado:

- servico dedicado em `src/audit/audit_log_service.py`;
- chamadas seguras e nao bloqueantes a partir de fluxos do app, como `app_ai_chat.py`, `src/ui/header.py`, `src/auth/user_service.py`, `src/auth/pending_registration_service.py`, `src/auth/password_reset_service.py` e `src/auth/email_verification_service.py`;
- a visualizacao administrativa fica em `src/ui/admin_page.py` e a permissao de acesso e controlada por `src/auth/roles.py` e `src/ui/sidebar.py`.

Como visualizar/usar:

- execute `streamlit run app_ai_chat.py`;
- entre com um usuario autorizado (`role` igual a `admin` ou `super_admin`, ou `can_view_audit=true`);
- acesse a pagina **Auditoria** na sidebar;
- usuarios nao autenticados ou sem permissao nao veem nem acessam a pagina de auditoria.

## Integracoes Externas

O projeto usa integracoes externas reais ou configuraveis, sempre por variaveis de ambiente e sem versionar credenciais.

### Chat IA / Provedor LLM

- Uso: responder perguntas analiticas controladas sobre a view somente leitura `vw_data_sus_ia`.
- Implementacao: `src/ai/pandasai_runner.py`, `src/ai/datasus_ai.py`, `src/ai/prompt_guard.py`, `src/ai/simple_stats_runner.py`.
- Provedores suportados/configuraveis: OpenAI, Gemini e OpenRouter via PandasAI/LiteLLM.
- Variaveis principais: `AI_USE_LLM`, `AI_LLM_PROVIDER`, `AI_LLM_MODEL`, `AI_LLM_API_KEY`, `OPENAI_API_KEY`, `GEMINI_API_KEY`, `OPENROUTER_API_KEY`.
- Modo seguro/local: `AI_USE_LLM=false` usa respostas estatisticas simples sem chamar API externa.

### E-mail SMTP

- Uso: envio de codigo/link para cadastro, verificacao, alteracao de e-mail, recuperacao de senha e reativacao de conta.
- Implementacao: `src/auth/email_service.py`, integrado por `src/auth/pending_registration_service.py`, `src/auth/password_reset_service.py`, `src/auth/email_change_service.py`, `src/auth/email_verification_service.py` e `src/auth/account_reactivation_service.py`.
- Variaveis principais: `EMAIL_ENABLED`, `EMAIL_PROVIDER`, `EMAIL_FROM`, `EMAIL_SMTP_HOST`, `EMAIL_SMTP_PORT`, `EMAIL_SMTP_USERNAME`, `EMAIL_SMTP_PASSWORD`, `EMAIL_USE_TLS`, `APP_PUBLIC_BASE_URL`.
- Padrao seguro: `EMAIL_ENABLED=false`, sem envio real.

### Google OAuth / OpenID Connect

- Uso: login/cadastro com Google quando habilitado.
- Implementacao: `src/auth/google_oauth_service.py`, com integracao de usuario em `src/auth/user_service.py` e callback tratado em `app_ai_chat.py`.
- Variaveis principais: `GOOGLE_OAUTH_ENABLED`, `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `GOOGLE_REDIRECT_URI`.
- O sistema usa `google_sub` como identificador estavel e exige e-mail verificado pelo Google.

### MinIO / Object Storage para logo

- Uso: exibir o logo institucional da aplicacao quando houver uma URL publica ou assinada.
- Implementacao: `src/ui/styles.py` e `src/ui/sidebar.py`.
- Variavel preferida: `APP_LOGO_URL`.
- Fallback local versionado: `images/logo.png`.
- O bucket MinIO pode permanecer privado para upload/administracao; nesse caso use uma URL assinada ou uma rota publica controlada. Se a URL nao estiver publica/acessivel, o app usa `images/logo.png`. Credenciais MinIO nao devem ser expostas no app.

## Cobertura de Testes

A cobertura automatizada da avaliacao esta registrada em `cobertura/coverage-report.txt`.

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

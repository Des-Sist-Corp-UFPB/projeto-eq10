# OpenTelemetry e Grafana — EQ10

## Arquitetura e fluxo atual

```text
Navegador -> Nginx :8080 -> Streamlit :8501
                             +-> autenticação/auditoria -> PostgreSQL da aplicação
                             +-> Prompt Guard -> validação temporal
                                 -> vw_data_sus_ia (Neon/read-only)
                                 -> estatística simples -> LLM/fallback
                             +-> OTLP/HTTP opcional -> Alloy
                                  +-> Tempo (traces)
                                  +-> Prometheus (métricas)
                                  +-> Grafana (consulta/dashboard)
```

O Prompt Guard continua antes da leitura analítica. A instrumentação não muda
decisões, consultas, autenticação ou interface.

### Ordem real de startup

`Dockerfile.chat` executa `start.sh`. O script inicia o processo Streamlit em
background, espera por até 60 segundos o socket `127.0.0.1:8501` aceitar
conexões e somente então inicia o Nginx em `8080`. Assim, `/ping` continua
proxyando `/_stcore/health`, mas o Nginx não produz erros esperados de
`connection refused` durante o bootstrap.

Ao importar `app_ai_chat.py`, imediatamente depois de importar Streamlit e antes
dos serviços de negócio, `configure_telemetry()` é executado. A inicialização é
protegida por lock e flag de processo; reruns do Streamlit não duplicam
providers, processors, handlers, instrumentos nem `app.startup`.

## Sinais e privacidade

- Traces: `ai.request` e etapas de classificação, validação, carga, estatística
  e LLM; conexão/consulta analítica; autenticação e auditoria.
- Métricas: requisições/bloqueios/falhas/fallback/duração de IA, duração/erros
  de consulta, logins e falhas de login/e-mail.
- Logs: correlação por trace, span e serviço; exportação é opt-in.

Prompts, e-mails, IDs de usuário, SQL, URLs de banco, tokens e credenciais não
são atributos. Exceções são reduzidas a categorias. O header OTLP nunca é
registrado.

## Configuração institucional

```dotenv
OTEL_ENABLED=true
OTEL_SERVICE_NAME=dsc-eq10
OTEL_RESOURCE_ATTRIBUTES=service.namespace=dsc,deployment.environment=production
OTEL_TRACES_EXPORTER=otlp
OTEL_METRICS_EXPORTER=otlp
OTEL_LOGS_EXPORTER=otlp
OTEL_EXPORTER_OTLP_PROTOCOL=http/protobuf
OTEL_EXPORTER_OTLP_ENDPOINT=<endpoint-de-ingestao-confirmado>
OTEL_EXPORTER_OTLP_HEADERS=Authorization=Basic <credencial-base64>
OTEL_EXPORTER_OTLP_TIMEOUT=10000
```

Valores reais ficam somente no gerenciador de segredos ou `.env.prod` fora do
Git. `OTEL_ENABLED=false` é o padrão do código; o Compose de produção ativa
explicitamente a telemetria.

A URL chamada “Panel” pode ser apenas a interface Grafana. O professor deve
confirmar o endpoint OTLP/HTTP e se a base inclui `/otlp`. O SDK acrescenta
`/v1/traces`, `/v1/metrics` e `/v1/logs`. Não use a URL do painel como ingestão
sem confirmação e não execute comandos verbosos que imprimam headers.

Para o endpoint global `https://otel.dsc.rodrigor.com`, os exporters usam:

- `https://otel.dsc.rodrigor.com/v1/traces`;
- `https://otel.dsc.rodrigor.com/v1/metrics`;
- `https://otel.dsc.rodrigor.com/v1/logs`.

Se a base terminar em `/otlp`, o resultado será `/otlp/v1/<signal>`. Se já
terminar no caminho específico `/v1/traces`, `/v1/metrics` ou `/v1/logs`, o
código não duplica o sufixo.

Use o header percent-encoded:

```dotenv
OTEL_EXPORTER_OTLP_HEADERS=Authorization=Basic%20<base64>
```

O parser do SDK decodifica `%20` para o espaço do header HTTP. A versão atual é
liberal e também pode aceitar espaço literal, mas `%20` é o formato aderente à
especificação e evita diferenças entre shells, Compose e versões do SDK.

## Deploy no servidor do professor

O workflow não possui acesso a um shell remoto arbitrário. A chave
`SSH_DEPLOY_KEY` usa um comando forçado no servidor: o Actions envia apenas
`actor:GITHUB_TOKEN` para o script de deploy puxar a imagem do GHCR. O
repositório não contém o script `~/ssh/deploy`, portanto seus detalhes internos
não podem ser alterados daqui. O contrato documentado é que ele aplica
`docker-compose.prod.yml`.

O serviço `app` desse Compose carrega `.env.prod`. Os valores OTEL não secretos
e estáveis estão no próprio Compose; somente estes dois valores devem ser
acrescentados ao `.env.prod` já existente:

```dotenv
OTEL_EXPORTER_OTLP_ENDPOINT=<endpoint-OTLP-institucional-confirmado>
OTEL_EXPORTER_OTLP_HEADERS=Authorization=Basic <credencial-fornecida>
```

O administrador deve editar o arquivo diretamente no servidor, sem recriá-lo e
sem remover as variáveis `AUTH_*`, `AI_*`, `EMAIL_*` existentes:

```bash
cd <diretorio-do-deploy-eq10>
chmod 600 .env.prod
${EDITOR:-vi} .env.prod
docker compose -f docker-compose.prod.yml up -d --pull always --force-recreate app
```

Não use `echo`, `set -x`, `docker inspect ...Config.Env`, `env`, `printenv` ou
`cat .env.prod` para essa operação. Nenhum novo GitHub Secret é necessário:
continuam necessários apenas `SSH_USERNAME` e `SSH_DEPLOY_KEY`; o token do GHCR
é o `GITHUB_TOKEN` efêmero fornecido pelo Actions.

Após o redeploy, este log é seguro e não contém URL ou header:

```bash
docker compose -f docker-compose.prod.yml logs --tail=200 app |
  grep "OpenTelemetry status"
```

O resultado esperado é:

```text
OpenTelemetry status | enabled=true | service_name=dsc-eq10 | endpoint_configured=true | headers_configured=true | provider_type=sdk | processor_configured=true | protocol=http/protobuf | initialization=configured
```

O status usa nível WARNING deliberadamente porque é emitido antes de o
Streamlit configurar o logging. Depois gere uma
pergunta permitida e procure no Tempo por
`resource.service.name = "dsc-eq10"`. Se a inicialização estiver configurada,
mas não houver traces, o administrador deve confirmar com o professor o
endpoint de ingestão, caminho `/otlp`, tipo de autorização e conectividade de
saída do container.

## Demonstração local

```bash
docker compose -f docker-compose.observability.yml up -d
docker compose -f docker-compose.chat.yml -f docker-compose.observability.yml up -d --build
```

Use localmente:

```dotenv
OTEL_ENABLED=true
OTEL_SERVICE_NAME=dsc-eq10
OTEL_RESOURCE_ATTRIBUTES=service.namespace=dsc,deployment.environment=development
OTEL_EXPORTER_OTLP_ENDPOINT=http://alloy:4318
OTEL_LOGS_EXPORTER=none
```

Abra `http://localhost:3000`. Dashboard: **EQ10 / EQ10 — Observabilidade**.
Em *Explore > Tempo*, pesquise `resource.service.name = dsc-eq10`. Em
Prometheus consulte `{__name__=~"eq10_ai_requests_total(_total)?"}`.

## Validação

```bash
uv run pytest tests/test_observability.py
uv run pytest tests/test_datasus_ai.py tests/test_prompt_guard.py tests/test_ai_data_provider.py
uv run pytest tests/test_database_routing.py
uv run pytest tests/test_auth_user_service.py tests/test_password_reset_service.py tests/test_email_verification_service.py tests/test_account_reactivation_service.py
python -m py_compile app_ai_chat.py src/observability/telemetry.py src/ai/datasus_ai.py src/ai/data_provider.py
docker compose -f docker-compose.observability.yml config
git diff --check
```

Gere uma pergunta permitida e outra bloqueada. Confirme séries no Prometheus e
traces no Tempo pelo serviço `dsc-eq10`.

## Verificação determinística e saúde

Uma inicialização SDK bem-sucedida emite uma vez por processo:

```text
app.startup
  app.framework=streamlit
  deployment.environment=production
  telemetry.verification=startup
```

Na área administrativa **Saúde e observabilidade**, o botão **Emitir trace de
verificação** chama `emit_verification_span()` e cria `observability.test`. A
mensagem da UI confirma somente a tentativa local de criação/flush; não afirma
que o Tempo recebeu o span.

O relatório unificado diferencia:

- banco da aplicação: usa somente `AUTH_DB_*`/`AUTH_DATABASE_URL`; falha torna
  a aplicação `unhealthy`;
- banco analítico: usa somente `AI_DB_*`/`AI_DATABASE_URL`, verifica sessão
  readonly, `vw_data_sus_ia`, permissão e `MAX(data)`; falha deixa a aplicação
  `degraded`, preservando login;
- OpenTelemetry: falha ou indisponibilidade nunca altera a disponibilidade.

Somente categorias, booleanos, bucket de latência, timestamp e a data máxima
permitida aparecem. Host, usuário, URL, SQL e mensagens PostgreSQL não aparecem.

## Produção, diagnóstico e limitações

O app pode enviar diretamente ao OTLP institucional ou a um Alloy intermediário.
Falhas do exportador não afetam a saúde e lotes podem ser descartados após o
timeout. `HealthService.run_all_checks()` e o log de startup expõem somente
enabled, service name, exporter configurado, protocolo, categoria do endpoint e
último resultado de inicialização.

Se não houver dados, confira endpoint de ingestão (não painel), protocolo,
DNS/TLS, autorização e o nome exato `dsc-eq10`. A stack local não inclui Loki;
logs locais permanecem no Docker. Não foi adicionada instrumentação específica
de Streamlit: os spans ficam nos limites de negócio. Confirmar o endpoint e
consultar o ambiente do professor exigem acesso institucional.

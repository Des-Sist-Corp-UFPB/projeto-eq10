# Liveness e readiness publicos

O container publica dois endpoints distintos pelo Nginx na porta `8080`:

- `GET /ping`: liveness leve. O Nginx encaminha para
  `http://127.0.0.1:8501/_stcore/health` e confirma que o Streamlit responde.
- `GET /health`: readiness do banco principal. O Nginx encaminha para um
  servidor HTTP interno em `127.0.0.1:8502`, que executa `SELECT 1` usando o
  provider autoritativo `get_auth_engine()` e somente `AUTH_DATABASE_URL` ou
  `AUTH_DB_*`.

O health nativo do Streamlit nao consulta o banco. Por isso `/ping` sozinho nao
prova que login, auditoria e persistencia da aplicacao estao prontos.

## Respostas

Banco da aplicacao acessivel:

```http
HTTP/1.1 200 OK
Content-Type: application/json
Cache-Control: no-store

{"status":"healthy","database":"connected"}
```

Banco da aplicacao indisponivel, configuracao ausente ou timeout:

```http
HTTP/1.1 503 Service Unavailable
Content-Type: application/json
Cache-Control: no-store

{"status":"unhealthy","database":"unavailable"}
```

`HEAD /health` devolve o mesmo status sem corpo. Caminhos desconhecidos recebem
404 e metodos nao suportados recebem 405. Nenhuma resposta inclui excecao, SQL,
host, usuario, banco, URL ou credencial.

O banco analitico, OpenTelemetry e Umami nao participam desse resultado. Uma
falha no Neon analitico pode degradar o Chat IA e aparecer no painel
administrativo sem tornar `/health` indisponivel.

## Timeout, carga e operacao

O processo de readiness reutiliza um engine SQLAlchemy com `pool_pre_ping`.
Conexao e espera pelo pool sao limitadas a cinco segundos. O Nginx usa timeout
de conexao de cinco segundos e leitura de seis segundos. O resultado tem cache
interno de cinco segundos para evitar uma nova conexao a cada probe; falhas nao
ficam ocultas por mais que esse intervalo.

O processo escuta somente em `127.0.0.1:8502`. A porta não e publicada pelo
Compose. `start.sh` inicia os tres processos e trata Streamlit e Nginx como
componentes criticos: a saida de um deles encerra o container. Readiness e
isolado; se ele falhar, `/ping` e o app continuam acessiveis e o Nginx devolve
o JSON seguro de indisponibilidade com HTTP 503 em `/health`.

O `HEALTHCHECK` do Docker permanece em `/ping`. Ele representa liveness e evita
reinicios por indisponibilidade de componentes nao essenciais. A readiness do
banco principal deve ser monitorada externamente por `/health`.

## Validacao

```bash
curl -i https://eq10.dsc.rodrigor.com/ping
curl -i https://eq10.dsc.rodrigor.com/health
curl -I https://eq10.dsc.rodrigor.com/health
```

O avaliador deve observar HTTP 200 e o JSON minimo acima em `/health`. O span
seguro `health.application.database` usa somente os atributos
`health.endpoint=readiness`, `health.result` e `health.category`.

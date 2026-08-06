# Liveness, diagnóstico e readiness — FastAPI

A aplicação primária em produção é FastAPI/Uvicorn, servida pelo Nginx do
mesmo container:

```text
cliente -> porta pública do host -> container:8080 (Nginx)
                                      -> 127.0.0.1:8811 (Uvicorn/FastAPI)
```

O serviço oficial do Compose é `app`, publicado apenas em
`127.0.0.1:8110:8080`. A porta 8811 não é exposta pelo container.

## Contratos

| Mecanismo | Semântica | Banco | HTTP |
|---|---|---:|---:|
| `GET /ping` | liveness do Nginx e FastAPI | não | 200 |
| `GET /healthcheck` | heartbeat diagnóstico seguro | aplicação e analítico | sempre 200 |
| `GET /health` | readiness do banco da aplicação | `AUTH_DB_*` / `AUTH_DATABASE_URL` | 200 ou 503 |

`/ping` retorna somente `{"status":"ok"}` e é usado pelo `HEALTHCHECK` do
`Dockerfile.fastapi` e, por padrão, pelo verificador pós-deploy do GitHub
Actions. O probe interno usa `/app/.venv/bin/python` e uma requisição HTTP
direta por socket ao Nginx, sem consultar banco e sem respeitar proxies de
ambiente.

`/healthcheck` permanece HTTP 200 para que seus detalhes seguros possam ser
lidos mesmo quando um componente está degradado.

`/health` executa `SELECT 1` no banco de autenticação. Retorna:

```json
{"status":"healthy","database":"connected"}
```

ou, com HTTP 503:

```json
{"status":"unhealthy","database":"unavailable"}
```

O banco analítico, OpenTelemetry e Umami não alteram a resposta de readiness.

## Inspeção segura de um container unhealthy

Não é necessário conhecer previamente o nome do container:

```bash
docker ps --format 'table {{.Names}}\t{{.Image}}\t{{.Status}}\t{{.Ports}}'
docker inspect --format '{{json .State.Health}}' <container>
docker inspect --format '{{json .Config.Healthcheck}}' <container>
docker exec <container> /app/.venv/bin/python /app/scripts/container_liveness.py
```

Probes internos, sem imprimir ambiente:

```bash
docker exec <container> /app/.venv/bin/python -c "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8811/ping', timeout=3).status)"
docker exec <container> /app/.venv/bin/python -c "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8080/ping', timeout=3).status)"
```

O workflow fixa `APP_HEALTH_URL` em
`https://eq10.dsc.rodrigor.com/ping`; esse também é o valor padrão de
`scripts/verify_deploy_health.py`. Assim, uma variável antiga do repositório
não consegue trocar liveness por uma rota dependente de banco.

O monitor do portal do professor deve usar `/ping` para disponibilidade. O
endpoint configurado fora do repositório precisa ser confirmado no ambiente do
professor; não é inferido pela aplicação.

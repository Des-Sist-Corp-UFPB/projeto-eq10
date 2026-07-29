# Stack local de observabilidade

Execute a partir da raiz:

```bash
docker compose -f docker-compose.observability.yml up -d
```

No app use `OTEL_ENABLED=true`, `OTEL_SERVICE_NAME=dsc-eq10` e
`OTEL_EXPORTER_OTLP_ENDPOINT=http://alloy:4318`. O Grafana fica em
`http://localhost:3000` (credenciais locais padrão `admin`/`admin`,
substituíveis por variáveis).

Esta stack é somente para demonstração local e não contém credenciais reais.

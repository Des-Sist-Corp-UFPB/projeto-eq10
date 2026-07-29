# Stack local de observabilidade

Esta stack é exclusivamente para demonstração local. A produção institucional
usa `https://otel.dsc.rodrigor.com`, autenticação Bearer mantida no `.env.prod`
protegido e os backends institucionais Tempo, Prometheus e Loki.

Execute a partir da raiz:

```bash
docker compose -f docker-compose.observability.yml up -d
```

No app use `OTEL_ENABLED=true`, `OTEL_SERVICE_NAME=dsc-eq10` e
`OTEL_EXPORTER_OTLP_ENDPOINT=http://alloy:4318`. O Grafana fica em
`http://localhost:3000` (credenciais locais padrão `admin`/`admin`,
substituíveis por variáveis).

Esta stack é somente para demonstração local e não contém credenciais reais.

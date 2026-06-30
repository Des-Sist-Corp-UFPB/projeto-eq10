# Relatorio de cobertura

Esta pasta contem o relatorio de cobertura exigido para a avaliacao.

O arquivo principal e:

- `coverage-report.txt`

Ele foi gerado com o runner local sem dependencias externas:

```powershell
python scripts/coverage_unittest.py --fail-under 85
```

Resultado atual registrado em `coverage-report.txt`: **85,5%** de cobertura total de linhas.

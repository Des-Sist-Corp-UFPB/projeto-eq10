# Testes automatizados e cobertura

Este projeto usa testes automatizados com `unittest`. Os testes devem rodar sem internet e sem chamar servicos reais como OpenRouter, Gemini, Google OAuth, SMTP, MinIO, Neon/PostgreSQL de producao ou qualquer credencial real.

## Preparar ambiente

Crie e ative um ambiente virtual Python compatível com o projeto. Depois instale as dependencias do `pyproject.toml` conforme o fluxo usado no ambiente local.

Para usar `coverage.py`, instale a ferramenta no ambiente:

```powershell
python -m pip install coverage
```

Se `coverage.py` nao estiver disponivel, use o runner local em `scripts/coverage_unittest.py`, que depende apenas da biblioteca padrao.

## Rodar todos os testes

```powershell
python -B -m unittest discover -s tests
```

## Rodar cobertura com coverage.py

```powershell
python -m coverage run -m unittest discover -s tests
python -m coverage report -m --fail-under=85
```

Para gerar relatorio HTML:

```powershell
python -m coverage html
```

O relatorio sera gerado em `htmlcov/`.

## Runner de cobertura sem dependencias extras

Quando `coverage.py` nao estiver instalado, rode:

```powershell
python scripts\coverage_unittest.py --fail-under 85
```

Para ver linhas faltantes:

```powershell
python scripts\coverage_unittest.py --show-missing
```

## Meta minima

A primeira avaliacao exige cobertura automatizada maior ou igual a 85%.

Comando recomendado para a avaliacao local:

```powershell
python scripts\coverage_unittest.py --fail-under 85
```

## Regras de seguranca dos testes

- Nao usar credenciais reais.
- Nao enviar e-mails reais.
- Nao chamar provedores LLM reais.
- Nao chamar Google OAuth real.
- Nao conectar em Neon/PostgreSQL de producao.
- Nao depender de internet.
- Usar mocks, fakes e bancos SQLite temporarios ou em memoria.
- Nao validar cobertura excluindo codigo importante apenas para inflar percentual.

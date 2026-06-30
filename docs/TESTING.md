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

## Logo da aplicacao

O logo exibido na interface deve vir, preferencialmente, de `APP_LOGO_URL`.
Esse valor precisa apontar para uma URL publica de leitura ou para uma URL
assinada valida do objeto, por exemplo um link direto para `logo.png`.

O bucket MinIO pode continuar privado para uploads e administracao. Nesse caso,
nao use a URL do console/browser privado como logo publico. Gere uma URL
assinada ou configure uma URL publica segura em `APP_LOGO_URL`.

O app nao deve expor credenciais do MinIO no frontend ou nos logs. Se
`APP_LOGO_URL` estiver ausente ou o navegador nao conseguir carregar a imagem,
a interface usa o arquivo local `images/logo.png`. Se o arquivo local tambem
falhar, a sidebar mostra o fallback textual com as iniciais.

Para ambientes com bucket privado, mantenha o bucket privado e publique apenas
uma URL assinada/temporaria ou uma rota publica controlada em `APP_LOGO_URL`.
O arquivo `images/logo.png` e um fallback estatico versionado no repositorio,
entao a producao nao depende de credenciais MinIO para exibir o logo.

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

## Camada de IA

Este projeto possui uma camada experimental e isolada de analise estatistica com PandasAI. Ela e somente leitura, nao executa a ETL principal e trabalha com DataFrames controlados da view `vw_data_sus_ia`.

Veja detalhes em: [docs/IA_PANDASAI.md](docs/IA_PANDASAI.md)

Interface experimental: `streamlit run app_ai_chat.py`

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

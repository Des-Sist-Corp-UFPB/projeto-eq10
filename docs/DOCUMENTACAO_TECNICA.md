# Documentacao Tecnica - SEC-MME Analise de Dados SIA/DATASUS

## Visao Geral

Este repositorio contem um pipeline Python de ETL para dados ambulatoriais do SIA/DATASUS e um projeto Power BI para analise dos dados carregados em PostgreSQL.

O fluxo principal busca dados do grupo `PA` do SIA para a UF `PB`, salva uma copia bruta em Parquet, aplica filtros e padronizacoes, grava uma copia transformada e carrega a tabela final `data_sus` no banco. O projeto Power BI consome esse banco e organiza metricas de producao, valores, variacoes mensais e comparacoes anuais.

## Arquitetura

```text
SIA/DATASUS
    |
    | extract_data()
    v
data/sia_datasus.parquet
    |
    | transform_datasus()
    v
data/sia_datasus_transformed.parquet
    |
    | load_data_sus()
    v
PostgreSQL
    |
    v
Power BI
```

## Estrutura do Projeto

```text
.
|-- main.py
|-- send_archives.py
|-- pyproject.toml
|-- uv.lock
|-- Dockerfile
|-- docker-compose.yml
|-- README.md
|-- constants/
|   |-- constants.py
|-- src/
|   |-- extract.py
|   |-- transform.py
|   |-- load.py
|   |-- utils.py
|-- notebooks/
|   |-- teste.ipynb
|-- power bi/
|   |-- sia_datasus_secretaria.pbip
|   |-- sia_datasus_secretaria.Report/
|   |-- sia_datasus_secretaria.SemanticModel/
|   |-- Telas/
|-- docs/
|   |-- DOCUMENTACAO_TECNICA.md
```

## Dependencias

As dependencias estao declaradas em `pyproject.toml`:

- `pysus`: acesso aos arquivos publicos do DATASUS.
- `pandas`: manipulacao tabular.
- `pyarrow`: leitura e escrita de Parquet.
- `sqlalchemy`: conexao e execucao SQL.
- `psycopg2-binary`: driver PostgreSQL.
- `python-dotenv`: leitura de variaveis em `config/.env`.
- `requests`: suporte a requisicoes HTTP.
- `gdal`: dependencia geoespacial usada pelo ambiente do projeto.

A versao Python esperada e `>=3.10,<3.12`.

## Configuracao

Para execucao via Docker, crie um arquivo `.env` na raiz do projeto a partir de `.env.example`:

```env
user=seu_usuario
password=sua_senha
host=seu_host
database=seu_banco
```

O arquivo `.env` e carregado pelo Docker Compose via `env_file`. Para execucao Python direta, o codigo atual carrega `config/.env`; alternativamente, as mesmas variaveis podem estar exportadas no ambiente do shell. O repositorio ignora `.env` e `config/.env` pelo `.gitignore`, entao as credenciais nao devem ser versionadas.

A conexao atual e montada no formato:

```text
postgresql://user:password@host/database?sslmode=require&channel_binding=require
```

## Pipeline Principal

O ponto de entrada e `main.py`.

Etapas executadas:

1. Inicializa o cliente `SIA().load()`.
2. Calcula o periodo-alvo com `get_target_period(months_delay=2)`.
3. Consulta o banco para evitar recarga duplicada de `data_sus` no mesmo mes e ano.
4. Executa a extracao com `extract_data(sia)`.
5. Executa a transformacao com `transform_datasus(file_path)`.
6. Salva o resultado em `data/sia_datasus_transformed.parquet`.
7. Rele o Parquet transformado.
8. Carrega os dados no PostgreSQL com `load_data_sus('data_sus', df)`.

Comando:

```powershell
uv run python main.py
```

## Execucao com Docker

O projeto possui um `Dockerfile` baseado na imagem GDAL `3.8.4`, alinhada com a dependencia `gdal==3.8.4` do `pyproject.toml`.

Build da imagem:

```powershell
docker compose build
```

Execucao do pipeline principal:

```powershell
docker compose run --rm etl
```

Execucao manual do script de dimensoes:

```powershell
docker compose run --rm dimensoes
```

O Compose monta `./data` em `/app/data`, preservando os Parquets gerados entre execucoes. As variaveis de banco sao lidas do `.env` local, que nao deve ser commitado.

## Periodo-Alvo

O periodo-alvo e calculado em `src/utils.py`:

```python
get_target_period(months_delay=2)
```

Com a configuracao atual, a ETL tenta processar o mes de dois meses antes da data corrente. A funcao tambem trata virada de ano. Por exemplo, se executada em janeiro, o mes esperado passa para novembro do ano anterior.

## Extracao

Arquivo: `src/extract.py`

Funcao principal:

```python
extract_data(sia) -> Path
```

Comportamento:

- Busca arquivos do SIA com `group="PA"`, `uf="PB"` e `year=ano_alvo`.
- Seleciona o ultimo arquivo retornado pela listagem.
- Extrai o mes do nome do arquivo usando os dois ultimos caracteres antes da extensao.
- Compara o mes do arquivo com o mes esperado.
- Se o mes estiver correto, baixa o arquivo, converte para DataFrame e salva em `data/sia_datasus.parquet`.
- Se o mes nao estiver correto, registra aviso e retorna `None`.

## Transformacao

Arquivo: `src/transform.py`

Funcao principal:

```python
transform_datasus(file_path)
```

Etapas:

1. Le apenas as colunas definidas em `LIST_FILTER_COLUMNS`.
2. Renomeia as colunas conforme `DIC_RENAME_COLUMNS`.
3. Filtra municipios de atendimento definidos em `LIST_FILTER_CITIES`.
4. Filtra unidades CNES definidas em `LIST_UNITS`.
5. Ajusta tipos conforme `DIC_COLUMNS_TYPE`.

Colunas finais da fato `data_sus`:

| Coluna | Origem DATASUS | Tipo esperado |
| --- | --- | --- |
| `frequencia` | `PA_QTDAPR` | inteiro |
| `quantidade_apresentada` | `PA_QTDPRO` | inteiro |
| `valor_aprovado` | `PA_VALAPR` | float |
| `valor_apresentado` | `PA_VALPRO` | float |
| `cod_municipio_atendido` | `PA_UFMUN` | texto |
| `cod_municipio_residencia` | `PA_MUNPCN` | texto |
| `data` | `PA_MVM` | data |
| `cod_raca_cor` | `PA_RACACOR` | texto |
| `idade` | `PA_IDADE` | inteiro |
| `cod_unidade` | `PA_CODUNI` | texto |
| `cod_ocupacao` | `PA_CBOCOD` | texto |
| `cod_procedimento` | `PA_PROC_ID` | texto |
| `sexo` | `PA_SEXO` | texto |

## Filtros de Negocio

Arquivo: `constants/constants.py`

Municipios filtrados:

| Codigo IBGE | Municipio |
| --- | --- |
| `250150` | Bananeiras |
| `251250` | Queimadas |
| `250890` | Mamanguape |

As unidades filtradas ficam na lista `LIST_UNITS` e representam codigos CNES aceitos no recorte da analise.

## Carga

Arquivo: `src/load.py`

Funcoes:

```python
get_engine()
load_data_sus(table_name: str, df)
check_data_exists(table_name: str, ano: int, mes: int, date_column: str = "data") -> bool
```

`load_data_sus` usa `DataFrame.to_sql()` com:

- `if_exists='append'`
- `index=False`

Depois da carga, o codigo consulta a tabela inteira para registrar a quantidade total de registros.

`check_data_exists` verifica se ja existe algum registro para o ano e mes informados:

```sql
SELECT 1
FROM table_name
WHERE EXTRACT(YEAR FROM data) = :ano
  AND EXTRACT(MONTH FROM data) = :mes
LIMIT 1
```

Se a consulta falhar, por exemplo porque a tabela ainda nao existe, a funcao retorna `False` para permitir a primeira carga.

## Carga Manual de Dimensoes

Arquivo: `send_archives.py`

Este script le arquivos Parquet locais de dimensoes e envia para o banco usando `load_data_sus`. No estado atual, apenas a carga de `dim_unidade` esta ativa; as demais chamadas estao comentadas.

Arquivos esperados:

- `data/dim_ocupacao.parquet`
- `data/dim_procedimento.parquet`
- `data/dim_raca_cor.parquet`
- `data/dim_municipio.parquet`
- `data/dim_unidades.parquet`

Comando:

```powershell
uv run python send_archives.py
```

Observacao: o script importa `transform` de `src.transform`, mas a funcao existente no modulo se chama `transform_datasus`. Como esse import nao e usado no restante do script, ele pode ser removido ou corrigido.

## Modelo de Dados no Power BI

O projeto Power BI esta em `power bi/sia_datasus_secretaria.pbip`.

Tabelas principais do modelo semantico:

- `public data_sus`: tabela fato carregada pelo pipeline.
- `public dim_raca_cor`: dimensao de raca/cor.
- `public dim_unidade`: dimensao de unidades CNES.
- `public dim_ocupacao`: dimensao de ocupacoes.
- `public dim_procedimento`: dimensao de procedimentos.
- `public dim_municipio_atendimento`: dimensao de municipios de atendimento.
- `public dim_municipio_residencia`: dimensao de municipios de residencia.
- `dim_calendario`: dimensao calendario.
- `metricas`: tabela calculada para medidas DAX.

Relacionamentos:

| Origem | Destino |
| --- | --- |
| `data_sus.cod_raca_cor` | `dim_raca_cor.codigo` |
| `data_sus.cod_unidade` | `dim_unidade.codigo` |
| `data_sus.cod_ocupacao` | `dim_ocupacao.codigo` |
| `data_sus.cod_procedimento` | `dim_procedimento.codigo` |
| `data_sus.cod_municipio_atendido` | `dim_municipio_atendimento.codigo` |
| `data_sus.cod_municipio_residencia` | `dim_municipio_residencia.codigo` |
| `data_sus.data` | `dim_calendario.Date` |

Medidas centrais:

- `total_frequencia`
- `total_valor_aprovado`
- `total_valor_apresentado`
- `total_quantidade_apresentada`
- medidas de cards formatados
- medidas de variacao MoM
- medidas de variacao YoY
- medidas de comparacao entre ultimo mes, penultimo mes e mesmo mes do ano anterior
- `atualizacao_dados`

Paginas do relatorio:

- `Visao Geral`
- `Demografia`
- `Analise Mensal`
- `Analise Anual`
- paginas auxiliares de drill-through ou componentes, como `DC_graf_linha_FRE` e `DC_graf_linha_VP`

## Dados Gerados Localmente

Durante a execucao, o pipeline cria arquivos em `data/`:

- `data/sia_datasus.parquet`
- `data/sia_datasus_transformed.parquet`

A pasta `data/` esta ignorada pelo Git.

## Logs

O projeto usa `logging` com nivel `INFO`. Os principais eventos registrados sao:

- inicio e fim da ETL
- periodo-alvo
- validacao de duplicidade
- quantidade de arquivos encontrados no DATASUS
- arquivo selecionado
- numero de linhas extraidas e transformadas
- carga no banco
- erros com stack trace no pipeline principal

## Pontos de Atencao

- `src/load.py` cria o engine no momento do import. Se as variaveis de ambiente nao existirem, a falha pode acontecer antes da chamada explicita de carga.
- A senha e importada de `config/.env`, mas nao passa por `quote_plus`; senhas com caracteres especiais podem quebrar a URL de conexao.
- `extract_data` pode retornar `None`, mas `main.py` segue para transformar `data/sia_datasus.parquet`. Se a extracao nao ocorrer e o arquivo antigo existir, existe risco de processar um arquivo anterior.
- `send_archives.py` tem um import nao utilizado e possivelmente incorreto: `from src.transform import transform`.
- O codigo contem alguns textos de log com caracteres corrompidos, provavelmente por diferenca de encoding.
- A carga usa `append`; a protecao de duplicidade existe apenas para `data_sus` no fluxo principal.

## Checklist Operacional

Antes de rodar em producao:

1. Confirmar que `.env` existe para Docker ou que `config/.env` existe para execucao Python direta.
2. Confirmar que o banco possui as tabelas esperadas ou permissao para cria-las via `to_sql`.
3. Confirmar conectividade com o DATASUS.
4. Rodar `uv run python main.py`.
5. Conferir logs de validacao do periodo.
6. Conferir total de registros no banco.
7. Atualizar o Power BI, se aplicavel.

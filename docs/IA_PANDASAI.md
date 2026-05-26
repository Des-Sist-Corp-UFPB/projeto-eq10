# Camada de IA com integracao experimental ao PandasAI

## Objetivo

A camada `src/ai/` foi criada para permitir analises estatisticas com PandasAI sobre dados ja existentes no PostgreSQL, especialmente a tabela `data_sus`.

PandasAI esta integrado em modo experimental. A chamada so acontece depois das validacoes de prompt, mes disponivel e carregamento de um DataFrame controlado.

A IA nao participa da ETL principal. Ela nao extrai dados do DATASUS, nao transforma arquivos, nao carrega tabelas e nao altera o fluxo executado por `main.py`.

## Arquitetura

```text
DATASUS
-> ETL tradicional
-> PostgreSQL / tabela data_sus
-> camada src/ai/
-> DataFrame controlado
-> integracao experimental com PandasAI
```

PandasAI recebe apenas o DataFrame controlado vindo de `src/ai/data_provider.py`. PandasAI nao recebe conexao livre com o banco.

## Principios de Seguranca

- Separacao da ETL principal.
- Conexao propria para IA.
- Usuario PostgreSQL somente leitura.
- Allowlist de tabela.
- Allowlist de colunas.
- Limite maximo de meses.
- Limite maximo de linhas.
- Bloqueio de prompts fora do escopo.
- Verificacao de mes disponivel.
- Logs de perguntas.
- Limpeza de contexto quando PandasAI for chamado.
- Nenhuma escrita no banco.
- Nenhuma alteracao de codigo pela IA.
- Nenhuma coleta nova do DATASUS pela IA.

Observacao sobre linhas: o limite maximo de linhas existe como protecao operacional. Caso o volume dos ultimos 3 meses ultrapasse esse limite, a analise podera representar apenas parte dos dados carregados, dependendo da implementacao atual do provider.

## O que a IA Podera Fazer

- Responder perguntas estatisticas.
- Calcular totais, medias, rankings e comparacoes simples.
- Analisar apenas os ultimos 3 meses disponiveis.
- Informar quando um mes solicitado ainda nao esta no sistema.
- Responder apenas com base na tabela `data_sus`.

## O que a IA Nunca Deve Fazer

- Modificar banco de dados.
- Modificar codigo.
- Alterar estrutura do banco.
- Executar ETL.
- Coletar dados novos do DATASUS.
- Acessar arquivos Parquet como fallback.
- Acessar `.env`, senhas, tokens ou credenciais.
- Executar SQL livre pedido pelo usuario.
- Executar scripts, terminal ou comandos de sistema.
- Responder com dados fora do periodo permitido.

## Arquivos da Camada

- `src/ai/config.py`: define constantes como `AI_MAX_MONTHS`, `AI_MAX_ROWS`, `AI_ALLOWED_TABLES` e `AI_ALLOWED_COLUMNS`.
- `src/ai/prompt_guard.py`: bloqueia prompts perigosos ou fora do escopo estatistico.
- `src/ai/read_only_datasus.py`: cria conexao separada de leitura usando variaveis `AI_DB_*`.
- `src/ai/data_provider.py`: carrega um DataFrame controlado com ultimos 3 meses disponiveis, colunas permitidas e limite de linhas.
- `src/ai/month_checker.py`: detecta mes/ano no prompt e verifica se esse mes existe no banco.
- `src/ai/query_logger.py`: registra perguntas aceitas ou bloqueadas sem salvar credenciais.
- `src/ai/pandasai_runner.py`: concentra a integracao experimental com PandasAI e LiteLLM, recebendo apenas o DataFrame controlado.
- `src/ai/datasus_ai.py`: entrada publica da camada de IA; orquestra validacoes, carregamento controlado e chamada ao runner experimental.

### Periodo em `data_provider.py`

O periodo carregado por `src/ai/data_provider.py` e calculado com base na maior data disponivel no banco.

A consulta usa intervalo fechado no inicio e aberto no fim:

```sql
data >= :data_inicio
data < :data_fim_exclusiva
```

Por isso, o fim do periodo pode aparecer nas respostas como `ate antes de YYYY-MM-DD`. Exemplo: se a maior data disponivel estiver em marco de 2026, o periodo dos ultimos 3 meses pode ser descrito como `2026-01-01 ate antes de 2026-04-01`.

## Variaveis de Ambiente

Configure variaveis especificas para leitura dos dados pela IA:

```env
AI_DB_USER=ia_readonly
AI_DB_PASSWORD=senha_forte_aqui
AI_DB_HOST=seu_host
AI_DB_NAME=seu_banco
```

Essas variaveis devem apontar para um usuario PostgreSQL somente leitura. Nao inclua credenciais reais na documentacao nem em arquivos versionados.

## Variaveis de Ambiente do Modelo

Configure o modelo usado pela integracao experimental:

```env
AI_LLM_MODEL=gpt-4.1-mini
AI_LLM_API_KEY=sua_chave_do_modelo
```

`OPENAI_API_KEY` pode ser usado como fallback para `AI_LLM_API_KEY`. Nao inclua chaves reais em arquivos versionados.

## Integracao Experimental com PandasAI

PandasAI e chamado somente depois de:

1. `prompt_guard.py`
2. `month_checker.py`
3. `data_provider.py`

A integracao segue estas regras:

- PandasAI recebe apenas um DataFrame controlado.
- PandasAI nao recebe conexao direta com PostgreSQL.
- PandasAI nao participa da ETL.
- PandasAI nao coleta dados novos.
- PandasAI nao altera banco nem codigo.
- PandasAI nao deve manter historico entre perguntas.
- A chamada nao usa `follow_up`.
- O contexto deve ser descartado apos cada prompt; a implementacao cria os objetos dentro da funcao para evitar reuso persistente.

## Exemplo de Usuario PostgreSQL Somente Leitura

```sql
CREATE USER ia_readonly WITH PASSWORD 'senha_forte_aqui';

GRANT CONNECT ON DATABASE seu_banco TO ia_readonly;
GRANT USAGE ON SCHEMA public TO ia_readonly;
GRANT SELECT ON TABLE public.data_sus TO ia_readonly;

REVOKE INSERT, UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER
ON ALL TABLES IN SCHEMA public
FROM ia_readonly;

REVOKE CREATE ON SCHEMA public FROM ia_readonly;

ALTER DEFAULT PRIVILEGES IN SCHEMA public
GRANT SELECT ON TABLES TO ia_readonly;
```

## Fluxo Atual da Funcao perguntar_datasus

1. `validar_prompt`
2. `validar_mes_solicitado_no_prompt`
3. `load_controlled_datasus_dataframe`
4. `executar_pergunta_com_pandasai`
5. Log da pergunta

O PandasAI e executado apenas com o DataFrame retornado por `load_controlled_datasus_dataframe`.

## Testes

Execute os testes atuais com:

```powershell
python -m unittest tests.test_prompt_guard tests.test_ai_data_provider tests.test_ai_month_checker tests.test_datasus_ai tests.test_pandasai_runner tests.test_ask_datasus_ai_cli
```

Os testes usam mocks para evitar conexao real com PostgreSQL e chamada real ao modelo.

## Teste Manual via CLI

Use o script abaixo para chamar manualmente a entrada `perguntar_datasus`:

```powershell
python scripts/ask_datasus_ai.py "qual o total de valor aprovado por municipio?"
```

Para responder de verdade, sao necessarias:

- variaveis `AI_DB_*` configuradas;
- usuario readonly com acesso a tabela `data_sus`;
- `AI_LLM_API_KEY` ou `OPENAI_API_KEY` configurada;
- dependencias instaladas.

## Interface de Chat Experimental

A interface `app_ai_chat.py` usa Streamlit e e apenas uma camada visual para testar a funcao `perguntar_datasus()`.

O visual foi ajustado com inspiracao na tela criada no Figma Make: sidebar roxa fixa, item de Chat destacado, item de Estatisticas secundario, banner superior em gradiente roxo/azul, cards claros e chips lilas de sugestoes. As imagens PNG do Power BI existentes no projeto permanecem apenas como referencia visual historica: elas nao sao modificadas, movidas, renomeadas ou alteradas pelo chat.

Ela nao acessa o banco diretamente, nao executa a ETL, nao modifica o Power BI e nao altera arquivos de dados. Todo o fluxo de seguranca continua concentrado na camada `src/ai/`.

Para rodar:

```powershell
python -m streamlit run app_ai_chat.py
```

Nesta fase, a interface usa a integracao experimental com PandasAI ja encapsulada em `src/ai/datasus_ai.py`.

## Status Atual

A camada chama PandasAI em modo experimental. O fluxo atual mantem dados controlados e validacoes antes da chamada de IA.

## Proximos Passos

1. Validar respostas com dados reais em ambiente controlado.
2. Revisar seguranca da execucao do PandasAI.
3. Avaliar isolamento adicional para execucao de codigo gerado.
4. Adicionar documentacao de uso para usuarios finais.

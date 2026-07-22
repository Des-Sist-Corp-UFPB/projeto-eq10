# Camada de IA com integracao experimental ao PandasAI

## Objetivo

A camada `src/ai/` foi criada para permitir analises estatisticas com PandasAI sobre dados ja existentes no PostgreSQL, usando como fonte principal a view `vw_data_sus_ia`.

PandasAI esta integrado em modo experimental. A chamada so acontece depois das validacoes de prompt, mes disponivel e carregamento de um DataFrame controlado.

A IA nao participa da ETL principal. Ela nao extrai dados do DATASUS, nao transforma arquivos, nao carrega tabelas e nao altera o fluxo executado por `main.py`.

## Arquitetura

```text
DATASUS
-> ETL tradicional
-> PostgreSQL / view vw_data_sus_ia
-> camada src/ai/
-> DataFrame controlado
-> integracao experimental com PandasAI
```

PandasAI recebe apenas o DataFrame controlado vindo de `src/ai/data_provider.py`. PandasAI nao recebe conexao livre com o banco.

## Principios de Seguranca

- Separacao da ETL principal.
- Conexao propria para IA.
- Usuario PostgreSQL somente leitura.
- Allowlist de fonte de dados.
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
- Responder apenas com base na view `vw_data_sus_ia`.

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
- `src/ai/read_only_datasus.py`: cria conexao separada de leitura usando `AI_DATABASE_URL` ou variaveis `AI_DB_*`.
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

## Fonte de Dados da IA

A camada de IA consulta a view `vw_data_sus_ia`. Essa view enriquece os registros da fato `data_sus` com dimensoes legiveis para que as respostas usem nomes descritivos em vez de codigos.

A aplicacao nao cria, recria nem altera essa view. Ela apenas executa consultas `SELECT` sobre `vw_data_sus_ia` usando a conexao somente leitura configurada em `AI_DATABASE_URL` ou `AI_DB_*`.

O DataFrame controlado possui estas colunas:

| Coluna | Descricao |
| --- | --- |
| `data` | data do registro |
| `idade` | idade do paciente/usuario |
| `sexo` | sexo |
| `municipio_atendimento` | municipio onde ocorreu o atendimento |
| `municipio_residencia` | municipio de residencia |
| `raca_cor` | raca/cor |
| `unidade` | unidade de atendimento |
| `ocupacao` | ocupacao |
| `procedimento` | procedimento realizado |
| `frequencia` | frequencia |
| `quantidade_apresentada` | quantidade apresentada |
| `valor_apresentado` | valor apresentado |
| `valor_aprovado` | valor aprovado |

Regras de uso esperadas:

- perguntas sobre atendimento por municipio devem usar `municipio_atendimento`;
- perguntas sobre residencia dos pacientes devem usar `municipio_residencia`;
- perguntas sobre tipos de procedimento devem usar `procedimento`;
- perguntas sobre unidade de atendimento devem usar `unidade`;
- perguntas por raca/cor devem usar `raca_cor`.

## Variaveis de Ambiente

Configure variaveis especificas para leitura dos dados pela IA:

```env
AI_DB_USER=ia_readonly
AI_DB_PASSWORD=senha_forte_aqui
AI_DB_HOST=seu_host
AI_DB_PORT=5432
AI_DB_NAME=seu_banco
```

Essas variaveis devem apontar para um usuario PostgreSQL somente leitura. Nao inclua credenciais reais na documentacao nem em arquivos versionados.

## Variaveis de Ambiente do Modelo

Configure o modelo usado pela integracao experimental:

```env
AI_USE_LLM=false
AI_FALLBACK_TO_SIMPLE=true
AI_LLM_PROVIDER=openai
AI_LLM_MODEL=gpt-4.1-mini
AI_LLM_API_KEY=sua_chave
AI_DEBUG_SAFE=false

# Exemplo Gemini:
# AI_LLM_PROVIDER=gemini
# AI_LLM_MODEL=gemini/gemini-2.0-flash
# AI_LLM_API_KEY=sua_chave_gemini

# Exemplo OpenRouter:
# AI_LLM_PROVIDER=openrouter
# AI_LLM_MODEL=openrouter/openrouter/free
# AI_LLM_API_KEY=sua_chave_openrouter
```

`AI_LLM_PROVIDER` define o provedor usado pelo LiteLLM. Os valores suportados sao `openai`, `gemini` e `openrouter`.

Para OpenAI, `AI_LLM_API_KEY` e a chave usada pela camada experimental de IA. `OPENAI_API_KEY` pode ser usado como fallback quando `AI_LLM_API_KEY` nao estiver definido. Quando `AI_LLM_API_KEY` existir e `OPENAI_API_KEY` nao estiver definido no ambiente, o runner tambem define `OPENAI_API_KEY` em memoria para compatibilidade com LiteLLM/OpenAI.

Para Gemini, use `AI_LLM_PROVIDER=gemini`. A chave pode vir de `AI_LLM_API_KEY` ou `GEMINI_API_KEY`. O modelo deve usar o prefixo `gemini/`; se o valor for informado sem esse prefixo, a camada adiciona o prefixo antes de chamar LiteLLM.

Para OpenRouter, use `AI_LLM_PROVIDER=openrouter`. A chave pode vir de `AI_LLM_API_KEY` ou `OPENROUTER_API_KEY`. O modelo deve usar o prefixo `openrouter/`; se `AI_LLM_MODEL` estiver vazio, o padrao usado e `openrouter/openrouter/free`.

`AI_DEBUG_SAFE=false` e o padrao recomendado. Quando definido como `true`, erros seguros da chamada PandasAI/LiteLLM podem incluir apenas o nome da classe da excecao, sem stack trace e sem credenciais. Use esse modo somente para diagnostico local.

Nao inclua chaves reais em arquivos versionados.

`AI_USE_LLM=false` ativa o modo estatistico simples local. Nesse modo, a camada nao importa, instancia nem chama PandasAI, LiteLLM, OpenAI, Gemini ou qualquer API externa, e tambem nao exige `AI_LLM_API_KEY`.

Para ativar o modo com PandasAI/LiteLLM, defina:

```env
AI_USE_LLM=true
```

ChatGPT Plus nao inclui creditos da API. Mesmo com uma assinatura ativa no ChatGPT, chamadas via LiteLLM/OpenAI API podem falhar com `RateLimitError` ou erro de billing quando nao houver credito ou faturamento configurado na plataforma de API. Gemini, OpenAI e OpenRouter tambem podem retornar erros de quota, credito, limite ou indisponibilidade temporaria. Modelos gratuitos do OpenRouter podem ter limites proprios de uso e disponibilidade. Nesse caso, use `AI_USE_LLM=false` para testar perguntas estatisticas simples localmente.

`AI_FALLBACK_TO_SIMPLE=true` permite que a camada tente o modo estatistico simples quando o LLM falhar por limite, quota, credito, billing ou indisponibilidade temporaria. Com `AI_FALLBACK_TO_SIMPLE=false`, a camada retorna apenas uma mensagem segura explicando o limite da API.

Observacao: o LiteLLM pode emitir warnings sobre `botocore` ausente quando dependencias opcionais de AWS Bedrock/SageMaker nao estao instaladas. Esses warnings nao significam necessariamente falha quando o provedor usado for OpenAI.

## Modos de Execucao

### Modo LLM

Com `AI_USE_LLM=true`, a camada chama PandasAI/LiteLLM depois das validacoes e do carregamento do DataFrame controlado. Esse modo permite perguntas mais flexiveis e pode usar OpenAI, Gemini ou OpenRouter, mas depende de chave de API, modelo valido, dependencias instaladas e limite/credito/billing disponivel no provedor.

Se a API retornar erro de limite, quota, credito, billing ou indisponibilidade temporaria, a resposta deve ser segura. Quando `AI_FALLBACK_TO_SIMPLE=true`, o sistema tenta responder pela estatistica simples usando o mesmo DataFrame controlado.

### Modo Estatistico Simples

Com `AI_USE_LLM=false`, a camada nao chama PandasAI nem LiteLLM. Ela usa apenas pandas sobre o DataFrame controlado retornado por `load_controlled_datasus_dataframe()`.

Esse modo simples e o fallback mais confiavel quando provedores externos estao sem credito, com limite excedido ou temporariamente indisponiveis.

O suporte inicial cobre:

- total de `valor_aprovado` por municipio de atendimento;
- total de `frequencia` por sexo;
- unidades com maior `quantidade_apresentada`;
- media de idade;
- total geral de `valor_aprovado`;
- contagem de registros.
- rankings basicos por municipio de atendimento, municipio de residencia, unidade, procedimento, raca/cor, ocupacao ou sexo.

Perguntas fora desse conjunto retornam uma mensagem amigavel informando que ainda nao estao disponiveis no modo simples.

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
- Erros de PandasAI/LiteLLM retornam mensagem segura, sem chave, senha, URL de banco ou stack trace.

## Exemplo de Usuario PostgreSQL Somente Leitura

```sql
CREATE USER ia_readonly WITH PASSWORD 'senha_forte_aqui';

GRANT CONNECT ON DATABASE seu_banco TO ia_readonly;
GRANT USAGE ON SCHEMA public TO ia_readonly;
GRANT SELECT ON public.vw_data_sus_ia TO ia_readonly;

REVOKE INSERT, UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER
ON ALL TABLES IN SCHEMA public
FROM ia_readonly;

REVOKE CREATE ON SCHEMA public FROM ia_readonly;

ALTER DEFAULT PRIVILEGES IN SCHEMA public
GRANT SELECT ON TABLES TO ia_readonly;
```

Se o usuario readonly tiver outro nome no ambiente, ajuste o comando. O ponto essencial e garantir permissao equivalente a:

```sql
GRANT SELECT ON vw_data_sus_ia TO ia_readonly;
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
python -m unittest tests.test_prompt_guard tests.test_ai_data_provider tests.test_ai_month_checker tests.test_datasus_ai tests.test_pandasai_runner tests.test_simple_stats_runner tests.test_ask_datasus_ai_cli
```

Os testes usam mocks para evitar conexao real com PostgreSQL e chamada real ao modelo.

## Teste Manual via CLI

Use o script abaixo para chamar manualmente a entrada `perguntar_datasus`:

```powershell
python scripts/ask_datasus_ai.py "qual o total de valor aprovado por municipio?"
```

Para responder de verdade, sao necessarias:

- variaveis `AI_DB_*` configuradas;
- usuario readonly com acesso de `SELECT` a view `vw_data_sus_ia`;
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

### Autenticacao da interface

A interface possui duas areas principais na sidebar: `Estatisticas` e `Chat IA`. A area `Estatisticas` e publica e direciona o usuario para o painel oficial do Power BI com os indicadores consolidados do SIA/DATASUS:

```text
https://app.powerbi.com/view?r=eyJrIjoiMzMyNGZiMDgtNTk1Yy00Y2E4LTgyOTItMTU4MzNiYWUxMDg3IiwidCI6IjlkYmYzMjZlLTIxODUtNGM3OC1iY2NhLTBmNTdmOTc4ZjNkYSJ9
```

A area `Chat IA` e protegida: o usuario precisa entrar ou criar conta para enviar perguntas ao chat inteligente. A sidebar e a fonte unica de navegacao principal da interface.

A persistencia de usuarios usa a tabela `usuarios`, com senha salva somente como hash seguro. A aplicacao espera os campos:

- `id`
- `nome`
- `email`
- `senha_hash`
- `role`
- `criado_em`
- `atualizado_em`
- `ultimo_login_em`
- `deleted_at`
- `deletado`
- `deletado_em`

Usuarios desativados devem receber `deletado = true` e `deletado_em` preenchido. Quando `deleted_at` existir em bases antigas, ele tambem e tratado como indicador de conta inativa. Eles nao aparecem como ativos e nao podem fazer login. O sistema nao deve remover usuarios fisicamente no fluxo normal.

A conexao de autenticacao deve usar `AUTH_DATABASE_URL` ou as variaveis completas `AUTH_DB_*` (`AUTH_DB_HOST`, `AUTH_DB_PORT`, `AUTH_DB_NAME`, `AUTH_DB_USER`, `AUTH_DB_PASSWORD`, `AUTH_DB_SSLMODE`). Em PostgreSQL nao local, use `AUTH_DB_SSLMODE=require`. `DATABASE_URL`, variaveis minusculas legadas (`host`, `database`, `user`, `password`, `port`) e SQLite local sao compatibilidade apenas para desenvolvimento/testes; em producao (`ENVIRONMENT=production`, `APP_ENV=production`, `ENV=production` ou `DEPLOY_ENV=production`) a aplicacao falha se `AUTH_*` nao estiver completo. O usuario de banco usado para autenticacao precisa ter permissao para criar/usar tabelas de aplicacao como `usuarios`, cadastros pendentes, tokens, auditoria e historico de chat. Isso e separado da permissao readonly usada pela camada de IA para consultar `vw_data_sus_ia`.

As variaveis `AI_DATABASE_URL` / `AI_DB_*` sao somente leitura e nao devem ser usadas para cadastro/login. Consulte `docs/DATABASE_ROUTING.md` para a tabela completa de ownership das duas bases.

## Rodando o chat com Docker

A configuracao Docker do chat usa Python 3.11 em ambiente isolado. Isso evita problemas em maquinas onde o Python local e 3.13, versao que nao e compativel com PandasAI/pandasai-litellm neste projeto.

Antes de subir o container, crie um `.env` local na raiz do projeto com as variaveis `AUTH_*`, `AI_DB_*`/`AI_DATABASE_URL`, `AI_LLM_*` e demais configuracoes da camada de IA. Esse arquivo nao deve ser commitado e nao e copiado para a imagem Docker; o compose apenas injeta as variaveis em tempo de execucao com `env_file: ./.env`.

Build da imagem do chat:

```powershell
docker compose -f docker-compose.chat.yml build
```

Rodar a interface Streamlit:

```powershell
docker compose -f docker-compose.chat.yml up
```

Diagnosticar se as variaveis estao chegando ao container sem expor credenciais:

```powershell
docker compose -f docker-compose.chat.yml run --rm chat-ai python -c "import os; print(os.getenv('AI_LLM_PROVIDER')); print(os.getenv('AI_LLM_MODEL')); print(bool(os.getenv('AI_LLM_API_KEY'))); print(os.getenv('AI_DB_USER')); print(os.getenv('AI_DB_HOST')); print(os.getenv('AI_DB_PORT'))"
```

Acesse no navegador:

```text
http://localhost:8501
```

Testar a CLI dentro do mesmo ambiente Docker:

```powershell
docker compose -f docker-compose.chat.yml run --rm chat-ai python scripts/ask_datasus_ai.py "qual o total de valor aprovado por municipio?"
```

O container do chat executa `start.sh`, que sobe o Streamlit em `0.0.0.0:8501` e o Nginx em `8080` apontando para `127.0.0.1:8501`. Ele nao executa `main.py`, nao coleta dados novos do DATASUS e nao modifica o banco; a camada de IA deve continuar apontando para um usuario PostgreSQL somente leitura em `AI_DATABASE_URL` ou `AI_DB_*`.

O endpoint `/ping` publicado pelo Nginx do container deve proxyar o healthcheck nativo do Streamlit em `/_stcore/health`. Assim, um HTTP 200 em `/ping` confirma que o Streamlit esta respondendo, e nao apenas que o Nginx esta vivo.

## Deploy do chat via GitHub Actions

O workflow `.github/workflows/deploy.yml` publica a imagem do chat no GitHub Container Registry usando `Dockerfile.chat` e aciona um deploy remoto via SSH. O workflow usa `runs-on: [self-hosted, dsc-selfhosted]`. Ele nao injeta variaveis `AUTH_*`, `AI_*` ou arquivo `.env` no container; essas configuracoes devem existir no servidor, por exemplo em `.env.prod` usado pelo `docker-compose.prod.yml`.

Apos o deploy SSH, o workflow executa `scripts/verify_deploy_health.py` e espera ate 120 segundos por uma resposta 2xx no endpoint publico. Por padrao, o script consulta `https://eq10.dsc.rodrigor.com/ping`; para outro endpoint, configure a variavel de repositorio `APP_HEALTH_URL`. O script imprime apenas codigo HTTP e categoria de erro, sem corpo de resposta, cabecalhos ou variaveis de ambiente.

Configure estes GitHub Secrets antes de executar o deploy:

- `SSH_USERNAME`
- `SSH_DEPLOY_KEY`

No servidor, configure `.env.prod` com:

- `AUTH_DATABASE_URL` ou `AUTH_DB_*` completos para o banco gravavel da aplicacao;
- `AI_DATABASE_URL` ou `AI_DB_*` completos para a base DATASUS readonly;
- `AI_LLM_*` quando `AI_USE_LLM=true`;
- `EMAIL_*`, `APP_PUBLIC_BASE_URL` e outros opcionais conforme o ambiente.

O container Streamlit escuta internamente em `0.0.0.0:8501`, e o Nginx do mesmo container publica a aplicacao em `8080`. No compose de producao, o mapeamento externo atual e `127.0.0.1:8110:8080`.

Se houver um Nginx externo no host, ele deve apontar para `127.0.0.1:8110`. Se houver um Nginx externo em outro container na mesma rede Docker, ele deve apontar para o servico/porta HTTP publicado pelo app, por exemplo `app:8080`. Um Nginx em container separado nao deve apontar para `localhost:8501`, pois `localhost` seria o proprio container do Nginx.

Comandos seguros para diagnostico no servidor, sem imprimir variaveis de ambiente:

```bash
docker compose -f docker-compose.prod.yml ps
docker compose -f docker-compose.prod.yml logs --tail=150 app
docker compose -f docker-compose.prod.yml exec -T app python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8501/_stcore/health', timeout=3)"
docker compose -f docker-compose.prod.yml exec -T app python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/ping', timeout=3)"
docker inspect "$(docker compose -f docker-compose.prod.yml ps -q app)" --format '{{.State.Status}} {{.State.ExitCode}} {{.State.Error}}'
docker inspect "$(docker compose -f docker-compose.prod.yml ps -q app)" --format '{{json .Config.Cmd}}'
docker inspect "$(docker compose -f docker-compose.prod.yml ps -q app)" --format '{{json .Config.Entrypoint}}'
```

Se a imagem publicada no GHCR estiver privada, o servidor precisa conseguir autenticar antes do `docker pull`. Ha duas opcoes operacionais: tornar o pacote publico nas configuracoes do GitHub Packages, ou fazer `docker login ghcr.io` no servidor com um usuario GitHub e um token com permissao de leitura de pacotes. Nao registre esse token no repositorio; guarde-o apenas no cofre de credenciais do servidor ou no mecanismo seguro usado pela operacao.

## Status Atual

A camada chama PandasAI em modo experimental. O fluxo atual mantem dados controlados e validacoes antes da chamada de IA.

## Proximos Passos

1. Validar respostas com dados reais em ambiente controlado.
2. Revisar seguranca da execucao do PandasAI.
3. Avaliar isolamento adicional para execucao de codigo gerado.
4. Adicionar documentacao de uso para usuarios finais.

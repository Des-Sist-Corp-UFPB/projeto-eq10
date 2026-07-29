# Analytics Umami no EQ10

## Finalidade e arquitetura

O Umami mede visitas, sessoes, navegacao entre paginas logicas e eventos de uso
do produto. Ele nao substitui o OpenTelemetry, que mede traces, metricas
tecnicas, latencia, erros, saude dos bancos e comportamento interno.

```text
Navegador / Streamlit -> tracker Umami -> servidor e painel institucional
Python / Streamlit -> OpenTelemetry SDK -> collector
                   -> Tempo / Prometheus / Loki -> Grafana
```

Painel institucional: <https://umami.dsc.rodrigor.com>. O login no painel e
manual e nunca e usado pelo aplicativo. O tracking precisa apenas da URL
publica do script e do identificador publico do website.

## Configuracao

```env
UMAMI_ENABLED=true
UMAMI_SCRIPT_URL=https://umami.dsc.rodrigor.com/script.js
UMAMI_WEBSITE_ID=339ab59d-d201-4b26-a7e5-e642385064f5
UMAMI_HOST_URL=https://umami.dsc.rodrigor.com
UMAMI_ALLOWED_DOMAIN=eq10.dsc.rodrigor.com
```

Se `UMAMI_ENABLED` estiver desligado, a URL for invalida ou o website ID estiver
ausente/invalido, o tracking fica desabilitado. Nenhuma dessas variaveis e
senha. Usuario e senha do painel nao devem ser colocados no `.env.prod`, no
Compose, no codigo ou no CI. Depois de mudar `.env.prod`, recrie ou reinicie o
container.

## Integracao com Streamlit

Streamlit nao oferece um template HTML normal para editar o `head`. Um
`st.components.v1.html` isolado em iframe tambem nao representaria a pagina
principal corretamente. Por isso `src/analytics/umami.py` usa um componente
oculto e controlado que acessa a pagina pai na mesma origem e acrescenta uma
unica tag `script` ao `parent.document.head`.

O elemento tem ID estavel e `st.session_state` impede nova injecao em reruns. O
tracker usa `data-auto-track=false`: page views sao chamadas explicitamente
apenas quando a pagina logica muda. Uma fila no navegador retem chamadas feitas
enquanto `script.js` ainda carrega.

Essa tecnica depende de o componente continuar autorizado a acessar
`window.parent`. Uma CSP que bloqueie o dominio do Umami ou uma futura mudanca
de isolamento do Streamlit pode impedir o tracking. As falhas sao ignoradas e
nunca bloqueiam a aplicacao ou seu WebSocket.

## Paginas logicas

- `/estatisticas`
- `/login`
- `/cadastro`
- `/recuperar-senha`
- `/chat-ia`
- `/auditoria`
- `/administracao` (reservada para fluxos administrativos que a utilizem)

Widgets, digitacao, graficos, polling e outros reruns nao geram page views. Uma
mudanca real de pagina gera uma nova view. Recarregar a aba pode criar uma nova
sessao e uma nova view, o que e esperado.

## Eventos

| Area | Eventos implementados |
|---|---|
| Autenticacao | `login_submitted`, `login_succeeded`, `login_failed`, `registration_submitted`, `registration_succeeded`, `password_reset_requested` |
| Chat IA | `ai_chat_opened`, `ai_question_submitted`, `ai_question_succeeded`, `ai_question_blocked`, `ai_question_failed`, `ai_fallback_used` |
| Estatisticas/admin | `statistics_viewed`, `audit_page_viewed`, `health_diagnostics_viewed`, `observability_trace_requested` |

`ai_fallback_used` usa a constante interna do aviso estruturado de fallback; o
conteudo da resposta e comparado localmente e nunca e enviado.

As unicas propriedades aceitas sao enumeradas no codigo: `result`,
`execution_mode`, `page` e `category`, cada qual com valores predefinidos.
Nomes de evento desconhecidos, chaves extras ou valores arbitrarios sao
recusados.

## Privacidade e diagnostico

Nunca sao enviados e-mail, nome, user ID, IP manual, prompt, resposta da IA,
SQL, municipio, procedimento, dado de paciente/saude, token, senha, URL com
query string, excecao ou stack trace. O payload nasce somente de constantes
permitidas; entradas do usuario nao sao encaminhadas.

O diagnostico administrativo mostra apenas flags, modo, categoria da ultima
tentativa local e website ID mascarado. Uma tentativa local nao prova
recebimento pelo Umami. Falha do Umami nao participa da saude do EQ10.

## Validacao

Os testes usam renderizadores falsos e nao acessam o servidor institucional:

```powershell
python -m pytest tests/test_umami_analytics.py tests/test_auth_modal_processing.py tests/test_coverage_focus.py -q
python -m py_compile app_ai_chat.py src/analytics/umami.py src/ui/auth_modal.py src/ui/admin_page.py
docker compose -f docker-compose.prod.yml --env-file .env.example config --quiet
git diff --check
```

Depois do deploy:

1. confirme que o app, login e Chat IA continuam normais;
2. abra Estatisticas e Login;
3. realize um login valido e uma tentativa invalida com credenciais de teste;
4. abra o Chat IA e envie uma pergunta permitida e outra bloqueada;
5. aguarde a ingestao e abra manualmente o painel institucional;
6. selecione o website EQ10 e confirme page views e eventos.

Eventos esperados: `statistics_viewed`, `login_succeeded`, `login_failed`,
`ai_question_submitted`, `ai_question_succeeded` e `ai_question_blocked`. Nao
declare sucesso remoto apenas porque a chamada JavaScript local ocorreu.

## Solucao de problemas

- **Status desabilitado:** confira `UMAMI_ENABLED`, URL HTTPS e website ID.
- **Sem page views:** confira o dominio, reinicie o container e teste sem
  bloqueador de conteudo.
- **Script bloqueado:** examine CSP, `script-src`, proxy e console do navegador.
- **Eventos duplicados:** confira `data-auto-track=false` e sessoes/abas abertas.
- **Page views sem eventos:** examine a chamada de rede depois da acao.
- **Painel vazio imediatamente:** aguarde a ingestao.

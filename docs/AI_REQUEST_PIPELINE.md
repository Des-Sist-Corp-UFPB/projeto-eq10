# Pipeline de perguntas estatísticas

```text
Prompt do usuário
  -> prompt_policy.classify_prompt (segurança + intenção + plano)
  -> validação do período
  -> data_provider (SELECT fixo, somente leitura, view permitida)
  -> simple_stats_runner (plano tipado)
  -> PandasAI, somente se o plano local não responder
  -> validação/formatação do resultado
  -> sanitização da UI
  -> resposta
```

`prompt_policy.py` é a única fonte de decisão sobre segurança e escopo.
`prompt_guard.py` é somente um adaptador para a API antiga. Não há SQL criado a
partir do prompt: `data_provider.py` usa um `SELECT` fixo, colunas permitidas, a
view `vw_data_sus_ia`, janela de tempo e limite de linhas.

O log interno `Pipeline IA` registra prompt (com segredos redigidos), intenção,
guard, validação, plano de agregação e decisão final. Ele não é enviado à UI.

## Causa raiz

Havia dois classificadores independentes. O guard aceitava termos estatísticos,
mas o runner exigia outras combinações exatas. Uma pergunta aceita pelo guard
podia falhar no runner, cair no LLM e sofrer uma falha de configuração, formato
ou execução. A UI convertia essas causas diferentes na mensagem genérica que
mencionava “segurança”, ocultando o estágio real.

A regressão reaparecia porque refatorações atualizavam apenas uma das listas ou
árvores de decisão. Agora um `PromptDecision` tipado é reutilizado pelo
orquestrador e pelos runners.

# Roadmap de Evolucao - SIA/DATASUS

Atualizado em: 2026-06-21

Este documento organiza os proximos passos tecnicos do app SIA/DATASUS. Ele nao substitui a documentacao tecnica existente; serve como roteiro de evolucao para estabilizar autenticacao, Chat IA, historico, auditoria e seguranca.

## 1. Estado Atual

O projeto ja possui uma base funcional importante:

- A pagina `Estatisticas` e publica.
- O painel Power BI oficial e usado para indicadores visuais consolidados.
- A pagina `Chat IA` e protegida por login.
- A camada de IA usa a view `vw_data_sus_ia`, com dados enriquecidos por nomes legiveis.
- O ambiente local com Docker e o deploy no servidor ja funcionam apos configuracao correta das variaveis de ambiente.
- Usuarios da aplicacao sao tratados separadamente das tabelas analiticas/brutas do DATASUS.
- O fluxo de autenticacao com cadastro, login, logout e perfil esta em evolucao.
- A sidebar e a fonte principal de navegacao do app.

## 2. Principio de Arquitetura

O projeto deve manter responsabilidades bem separadas:

- O Power BI e responsavel por dashboards visuais consolidados, indicadores, graficos e navegacao analitica publica.
- O app web e responsavel por acesso autenticado, Chat IA, sessao de usuario, perfil, historico futuro e auditoria.
- A IA nao deve modificar, recriar, apagar ou controlar livremente o banco de dados.
- O codigo deve executar apenas consultas e funcoes controladas, preferencialmente somente leitura para dados analiticos.
- Os dados de origem/analiticos do DATASUS nao devem ser modificados por fluxos de autenticacao, perfil ou historico de chat.
- Autenticacao, sessoes, perfis e historico futuro devem usar tabelas de aplicacao separadas.
- Credenciais, tokens, strings de conexao e chaves de provedores de IA nunca devem aparecer na interface nem em logs inseguros.

## 3. Roadmap Prioritario

### Phase 1 - P0 - Estabilizar Autenticacao

Objetivo: garantir que o acesso ao sistema seja confiavel antes de adicionar novas funcionalidades.

Tarefas:

- [ ] Confirmar que o cadastro cria usuario corretamente.
- [ ] Confirmar que o login funciona com senha correta.
- [ ] Confirmar que o logout limpa apenas a sessao autenticada.
- [ ] Confirmar que a sessao persiste ao alternar entre `Estatisticas`, `Chat IA` e modais.
- [ ] Confirmar que `Chat IA` continua protegido contra usuarios anonimos.
- [ ] Confirmar que `Estatisticas` continua publica.
- [ ] Manter erros amigaveis na UI e causas tecnicas seguras nos logs.

Criterios de aceite:

- [ ] Usuario permanece logado ao alternar de `Estatisticas` para `Chat IA`.
- [ ] Usuario anonimo nao consegue enviar perguntas ao Chat IA.
- [ ] Logout encerra sessao e volta ao estado deslogado.
- [ ] Erros de banco/autenticacao nao exibem credenciais ou tracebacks na tela.

### Phase 2 - P0 - Tabela de Usuarios e Soft Delete

Objetivo: consolidar armazenamento de usuarios sem misturar com dados DATASUS.

Tarefas:

- [ ] Confirmar que usuarios ficam em tabela separada `usuarios`.
- [ ] Confirmar que senhas sao armazenadas apenas como hash.
- [ ] Adicionar ou padronizar soft delete com campo recomendado pelo professor:

```sql
deletado BOOLEAN DEFAULT false
```

- [ ] Opcionalmente manter tambem:

```sql
deletado_em TIMESTAMP NULL
```

- [ ] Nunca remover usuarios fisicamente em fluxos normais da aplicacao.
- [ ] Ao desativar conta, definir `deletado = true`.
- [ ] Login deve permitir apenas usuarios com `deletado = false`.
- [ ] Listagens normais devem ocultar usuarios com `deletado = true`.

Criterios de aceite:

- [ ] Senha em texto puro nunca aparece na tabela `usuarios`.
- [ ] Usuario desativado nao consegue fazer login.
- [ ] Nenhum `DELETE` fisico e usado para remocao/desativacao de conta.
- [ ] Dados DATASUS nao sao alterados por operacoes de usuario.

### Phase 3 - P1 - Perfil e Gerenciamento de Conta

Objetivo: transformar o perfil em uma area simples e confiavel de gestao da conta.

Tarefas:

- [ ] Melhorar modal ou pagina de perfil.
- [ ] Exibir dados uteis para o usuario final:
  - `nome`;
  - `e-mail`.
- [ ] Ocultar ou reduzir destaque de `role`/`perfil` se nao for util ao usuario final.
- [ ] Manter acoes polidas:
  - Alterar nome;
  - Alterar e-mail;
  - Alterar senha;
  - Desativar conta.
- [ ] Exigir confirmacao antes de desativar conta.
- [ ] Alteracao de senha deve exigir senha atual.
- [ ] Alteracao de e-mail deve documentar verificacao como pendente se nao houver servico de e-mail.

Criterios de aceite:

- [ ] Usuario consegue alterar nome sem perder a sessao.
- [ ] Alteracao de senha exige senha atual.
- [ ] Acao de desativar conta exige confirmacao explicita.
- [ ] Usuario desativado deixa de acessar o Chat IA.

### Phase 4 - P1 - Polimento de UI

Objetivo: deixar a interface consistente, clara e profissional.

Tarefas:

- [ ] Finalizar estilo do modal de autenticacao.
- [ ] Corrigir ou remover icone de visibilidade de senha se for fragil.
- [ ] Finalizar estilo do menu de perfil.
- [ ] Manter feedbacks/toasts de sucesso limpos e claros.
- [ ] Manter mensagens de erro vermelhas e legiveis.
- [ ] Garantir que HTML bruto nunca apareca na tela.
- [ ] Manter a sidebar como unica fonte de navegacao principal.
- [ ] Manter identidade visual roxo/azul alinhada ao painel Power BI.

Criterios de aceite:

- [ ] Nao existe navegacao duplicada no conteudo principal.
- [ ] Botoes de login, perfil e logout tem aparencia consistente.
- [ ] Feedback de sucesso nao usa bloco escuro pesado.
- [ ] Nenhum HTML bruto aparece para o usuario.

### Phase 5 - P1 - Confiabilidade do Chat IA

Objetivo: reduzir falhas em perguntas comuns e manter respostas seguras.

Tarefas:

- [ ] Garantir que perguntas sugeridas funcionem.
- [ ] Manter input do chat fixo no final da conversa.
- [ ] Manter mensagens em ordem cronologica.
- [ ] Manter handlers/fallbacks estatisticos para perguntas comuns.
- [ ] Registrar causas tecnicas seguras para falhas da IA.
- [ ] Nao expor credenciais, tokens, tracebacks ou strings de conexao na interface.
- [ ] Preservar uso da view `vw_data_sus_ia`.

Criterios de aceite:

- [ ] Perguntas sugeridas retornam resposta util.
- [ ] Input nao some durante processamento.
- [ ] Loading aparece como balao da assistente.
- [ ] Falha tecnica gera mensagem amigavel na UI e log seguro no backend.

### Phase 6 - P2 - Historico de Chat e Auditoria

Objetivo: permitir rastreabilidade de interacoes sem armazenar dados sensiveis desnecessarios.

Tarefas:

- [ ] Criar tabela `chat_sessions`.
- [ ] Criar tabela `chat_messages`.
- [ ] Associar mensagens a `user_id`.
- [ ] Armazenar pergunta, resposta, status, modelo/provedor e timestamps.
- [ ] Considerar soft delete para historico:

```sql
deletado BOOLEAN DEFAULT false
deletado_em TIMESTAMP NULL
```

- [ ] Permitir que usuarios ocultem/removam historico proprio por soft delete.
- [ ] Evitar armazenar dados sensiveis alem do necessario.

Criterios de aceite:

- [ ] Cada conversa fica associada ao usuario autenticado.
- [ ] Historico pode ser ocultado sem exclusao fisica.
- [ ] Logs/historico nao armazenam senhas, tokens ou chaves.
- [ ] Falhas de IA podem ser auditadas por status e timestamp.

### Phase 7 - P2 - Health Checks e Diagnosticos

Objetivo: facilitar suporte local e em servidor sem expor segredos.

Tarefas:

- [ ] Adicionar diagnostico de app vivo.
- [ ] Adicionar diagnostico de conexao com banco.
- [ ] Validar se `vw_data_sus_ia` esta acessivel.
- [ ] Validar se configuracao de IA esta presente.
- [ ] Validar presenca de chave/provedor sem expor a chave.
- [ ] Se nao houver REST API, documentar diagnosticos como secao interna do Streamlit ou checks seguros.
- [ ] Manter `/ping` ou equivalente se ja existir.

Criterios de aceite:

- [ ] Diagnostico informa status sem exibir credenciais.
- [ ] Falha de banco e distinguida de falha de provedor de IA.
- [ ] Acesso a `vw_data_sus_ia` pode ser testado com consulta somente leitura.
- [ ] Checks sensiveis sao admin-only ou internos.

### Phase 8 - P2 - Revisao LGPD e Seguranca

Objetivo: documentar responsabilidades e reduzir risco juridico/operacional.

Tarefas:

- [ ] Documentar quais dados de usuario sao armazenados.
- [ ] Documentar por que esses dados sao armazenados.
- [ ] Documentar estrategia de hash de senha.
- [ ] Documentar estrategia de soft delete.
- [ ] Documentar que credenciais e segredos nao devem ser logados.
- [ ] Documentar que dados analiticos DATASUS sao tratados como somente leitura pelo app.
- [ ] Aplicar principio do menor privilegio para usuarios de banco.

Criterios de aceite:

- [ ] Existe uma secao clara de dados pessoais armazenados.
- [ ] Existe uma secao clara de retencao/desativacao.
- [ ] Logs nao contem senha, hash, token ou chave.
- [ ] Usuario do banco para IA continua somente leitura.

### Phase 9 - P3 - Melhorias Futuras Opcionais

Objetivo: registrar ideias sem transformar tudo em prioridade imediata.

Ideias:

- [ ] Recuperacao de senha com servico real de e-mail.
- [ ] Verificacao de e-mail para troca de e-mail.
- [ ] MinIO para arquivos/exportacoes se o app passar a gerar ou armazenar arquivos.
- [ ] Reconhecimento de intencao multilingue.
- [ ] Function calling/tools para consultas controladas.
- [ ] MCP server apenas como exploracao avancada futura.

Criterios de aceite:

- [ ] Nenhuma melhoria opcional bloqueia estabilizacao da autenticacao.
- [ ] Servicos externos so sao ativados com variaveis e permissoes documentadas.
- [ ] Funcionalidades futuras preservam o principio de consultas controladas.

## 4. Tabelas Sugeridas

### Tabelas da Aplicacao

Estas tabelas pertencem ao app web e nao devem ser misturadas com tabelas analiticas DATASUS.

#### `usuarios`

Uso: autenticacao, perfil e controle de acesso.

Campos recomendados:

- `id`
- `nome`
- `email`
- `senha_hash`
- `role`
- `criado_em`
- `atualizado_em`
- `ultimo_login_em`
- `deletado BOOLEAN DEFAULT false`
- `deletado_em TIMESTAMP NULL`

Observacoes:

- Senha deve ser sempre hash.
- E-mail ativo deve ser unico.
- Desativacao deve usar soft delete.

#### `chat_sessions`

Uso: agrupar conversas de um usuario.

Campos sugeridos:

- `id`
- `user_id`
- `titulo`
- `criado_em`
- `atualizado_em`
- `deletado BOOLEAN DEFAULT false`
- `deletado_em TIMESTAMP NULL`

#### `chat_messages`

Uso: armazenar mensagens de usuario e assistente.

Campos sugeridos:

- `id`
- `chat_session_id`
- `user_id`
- `role`
- `conteudo`
- `status`
- `criado_em`
- `deletado BOOLEAN DEFAULT false`
- `deletado_em TIMESTAMP NULL`

#### `ai_interactions` Opcional

Uso: auditoria tecnica de chamadas de IA.

Campos sugeridos:

- `id`
- `user_id`
- `chat_session_id`
- `provider`
- `model`
- `status`
- `erro_seguro`
- `duracao_ms`
- `criado_em`

### Tabelas e Views Analiticas DATASUS

Estas estruturas pertencem ao dominio analitico e devem permanecer separadas de autenticacao e historico:

- `data_sus`
- `dim_*`
- `vw_data_sus_ia`

Regra: autenticacao, perfil e historico de chat nao devem ser armazenados dentro de `data_sus`, `dim_*` ou `vw_data_sus_ia`.

## 5. Riscos e Perguntas Abertas

- Os usuarios estao no banco/schema correto em todos os ambientes?
- O servidor possui todas as variaveis de autenticacao e IA configuradas?
- A desativacao de conta deve usar apenas `deletado` ou tambem `deletado_em`?
- A verificacao de e-mail e obrigatoria agora ou fica para etapa futura?
- O historico de chat deve ser implementado agora ou apos a autenticacao ficar totalmente estavel?
- Health checks devem ser publicos, admin-only ou apenas internos?
- O usuario de banco da IA esta limitado a SELECT na view `vw_data_sus_ia`?
- Quem sera responsavel por operacoes administrativas de usuario, como reativacao?

## 6. Recomendacoes Imediatas

Proximas 3 tarefas recomendadas, em ordem:

1. Finalizar estabilizacao da autenticacao e validar o fluxo completo em ambiente local, Docker e servidor.
2. Padronizar soft delete de usuarios com `deletado BOOLEAN DEFAULT false` e, se aprovado, `deletado_em TIMESTAMP NULL`.
3. Implementar historico basico de chat com `chat_sessions` e `chat_messages`, ja planejando auditoria e soft delete.

## 7. Definicao de Pronto Geral

Um incremento deve ser considerado pronto quando:

- Mantem `Estatisticas` publica.
- Mantem `Chat IA` protegido.
- Nao altera dados analiticos DATASUS por fluxos de usuario.
- Nao expõe credenciais, tokens, senhas, hashes ou tracebacks na UI.
- Possui testes ou verificacao manual documentada.
- Possui logs tecnicos seguros para diagnostico.
- Preserva o papel do Power BI como painel visual consolidado.

# Roadmap de Evolucao - SIA/DATASUS

Atualizado em: 2026-06-22

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
- [ ] Ao desativar conta, limpar a sessao do usuario autenticado.
- [ ] Login deve permitir apenas usuarios com `deletado = false`.
- [ ] Listagens normais devem ocultar usuarios com `deletado = true`.
- [ ] Documentar que a acao visivel para o usuario deve ser `Desativar conta`, nao exclusao fisica.
- [ ] Reservar `Exclusao definitiva administrativa` ou `expurgo` para uma politica futura explicita, com trilha de auditoria, autorizacao e confirmacao.
- [ ] Permitir reativacao segura de conta desativada somente com prova de controle do e-mail.
- [ ] Configurar janela de reativacao automatica, por exemplo `ACCOUNT_REACTIVATION_WINDOW_DAYS`.

Comportamento recomendado para `Desativar conta`:

- Definir `deletado = true`.
- Opcionalmente definir `deletado_em = current timestamp`.
- Encerrar a sessao do usuario.
- Bloquear logins futuros.
- Ocultar o usuario em listagens comuns.
- Nunca executar `DELETE` fisico no fluxo normal do usuario.

Comportamento recomendado para reativacao:

- Nao criar uma nova conta quando o e-mail pertence a usuario desativado.
- Enviar codigo de reativacao por e-mail quando a conta estiver dentro da janela configurada.
- Armazenar apenas `codigo_hash`, nunca o codigo cru.
- Ao confirmar codigo valido, definir `deletado = false` e limpar `deletado_em`.
- Contas fora da janela devem exigir revisao administrativa futura ou politica de expurgo.
- Mensagens publicas de cadastro devem ser neutras para evitar enumeracao de contas.
- A interface nao deve revelar se o e-mail pertence a conta ativa, desativada, inexistente ou fora da janela antes da confirmacao por codigo.
- O estado "conta criada" ou "conta reativada" so pode aparecer depois da prova de controle do e-mail.

Por que usar soft delete:

- Preserva auditabilidade.
- Evita perda acidental de dados.
- Segue a sugestao do professor de usar um booleano para ocultar registros removidos.
- Permite investigar eventos de seguranca sem depender de backups.

Criterios de aceite:

- [ ] Senha em texto puro nunca aparece na tabela `usuarios`.
- [ ] Usuario desativado nao consegue fazer login.
- [ ] Nenhum `DELETE` fisico e usado para remocao/desativacao de conta.
- [ ] Usuario e marcado com `deletado = true` ao desativar a conta.
- [ ] Dados DATASUS nao sao alterados por operacoes de usuario.
- [ ] Conta desativada nao e recriada silenciosamente no cadastro.
- [ ] Reativacao exige confirmacao por e-mail.
- [ ] Cadastro usa mensagem publica neutra para e-mails ativos, desativados ou inexistentes.

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
- [ ] Adicionar `Desativar conta` como acao de conta quando o soft delete estiver padronizado.

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

### Phase 6 - P2 - Verificacao de E-mail

Objetivo: confirmar que o usuario controla o e-mail informado, sem tentar descobrir silenciosamente se o e-mail existe.

Nota: a estrategia de envio e provedores esta documentada em `docs/EMAIL_SERVICE_PLAN.md`.

Importante: o sistema nao deve tentar verificar se um e-mail existe por consulta externa ou comportamento invisivel. A verificacao deve provar controle do endereco por link ou codigo enviado ao usuario.

Implementacao inicial: a fundacao de verificacao foi adicionada com campos em `usuarios`, tabela `email_verification_tokens`, hash de token, expiracao, uso unico e modo fake/local. `EMAIL_VERIFICATION_REQUIRED=false` deve permanecer como padrao enquanto o envio real nao estiver configurado. Se o flag for ativado, o login continua permitido, mas o Chat IA fica bloqueado ate a verificacao para que o usuario ainda consiga acessar o perfil e reenviar a verificacao.

Campos/tabelas sugeridos:

```sql
usuarios.email_verificado BOOLEAN DEFAULT false
usuarios.email_verificado_em TIMESTAMP NULL
```

Tabela opcional:

```sql
email_verification_tokens
```

Fluxo recomendado:

- Usuario se cadastra.
- Sistema cria um token de verificacao.
- Sistema envia e-mail com link ou codigo.
- Usuario clica no link ou informa o codigo.
- Sistema define `email_verificado = true`.
- Sistema preenche `email_verificado_em`.
- Token expira em tempo limitado.
- Token so pode ser usado uma vez.

Requisitos de seguranca:

- Armazenar hash do token, nao o token puro, sempre que possivel.
- Token deve expirar.
- Token nao pode ser reutilizado.
- Nao revelar em mensagens publicas se um e-mail pertence a uma conta existente.
- Nao registrar tokens em logs.

Criterios de aceite:

- [ ] Usuario pode se cadastrar com `email_verificado = false`.
- [ ] E-mail de verificacao pode ser enviado.
- [ ] Token expira apos tempo limitado.
- [ ] Token nao pode ser reutilizado.
- [ ] Usuario verificado fica com `email_verificado = true`.

### Phase 7 - P2 - Recuperacao de Senha por E-mail

Objetivo: permitir redefinicao segura de senha sem revelar se o e-mail existe.

Nota: a estrategia de envio e provedores esta documentada em `docs/EMAIL_SERVICE_PLAN.md`.

Implementacao inicial: a fundacao de recuperacao de senha foi adicionada com tabela `password_reset_tokens`, hash de token, expiracao, uso unico, mensagem publica neutra e integracao com `EmailService` em modo fake/local. O envio real por SMTP/API continua desativado por padrao.

Fluxo recomendado:

- Usuario clica em `Esqueci minha senha`.
- Usuario informa o e-mail.
- UI sempre exibe mensagem neutra:

> Se houver uma conta com este e-mail, enviaremos instrucoes de recuperacao.

- Sistema cria token de redefinicao.
- Sistema envia e-mail de recuperacao.
- Usuario abre o link.
- Usuario define nova senha.
- Token expira em tempo limitado.
- Token so pode ser usado uma vez.

Tabela sugerida:

```sql
password_reset_tokens (
    id,
    user_id,
    token_hash,
    criado_em,
    expira_em,
    usado_em
)
```

Requisitos de seguranca:

- Nunca revelar se o e-mail existe.
- Nunca armazenar token puro.
- Nunca registrar token em log.
- Exigir senha nova forte o suficiente.
- Invalidar token apos uso.
- Salvar a nova senha apenas como hash.

Criterios de aceite:

- [ ] Mensagem neutra aparece mesmo se o e-mail nao existir.
- [ ] Token de redefinicao expira.
- [ ] Token de redefinicao nao pode ser reutilizado.
- [ ] Nova senha e salva como hash.
- [ ] Senha antiga deixa de funcionar apos redefinicao.

### Phase 8 - P2/P3 - Historico de Chat e Auditoria

Objetivo: permitir rastreabilidade de interacoes sem armazenar dados sensiveis desnecessarios.

Implementacao inicial: foram adicionadas as tabelas de aplicacao `chat_sessions` e `chat_messages`, com associacao por `user_id`, status por mensagem, timestamps e soft delete por `deletado`/`deletado_em`. A tabela `ai_interactions` fica pendente para uma etapa futura de auditoria de provedor/modelo/duracao.

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

### Phase 9 - P2 - Health Checks e Diagnosticos

Objetivo: facilitar suporte local e em servidor sem expor segredos.

Implementacao inicial: foi adicionado o modulo interno `src/diagnostics/health_service.py` com resultados estruturados e seguros para app, banco de aplicacao, tabelas de aplicacao, view `vw_data_sus_ia`, configuracao de IA e configuracao de e-mail. A implementacao nao cria rota publica nem pagina aberta de diagnostico; os checks ficam prontos para uso interno ou futura area administrativa. A validacao da view analitica usa apenas consulta `SELECT` pela conexao readonly da IA.

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

### Phase 10 - P2 - Revisao LGPD e Seguranca

Objetivo: documentar responsabilidades e reduzir risco juridico/operacional.

Documento de referencia: `docs/SECURITY_LGPD_REVIEW.md`.

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

### Phase 11 - P3 - Entrar com Google / OAuth

Objetivo: permitir login federado com Google sem quebrar o login por e-mail e senha.

Esta e uma funcionalidade maior e nao deve ser implementada antes de estabilizar cadastro, login, logout, sessoes, soft delete e configuracao segura de ambiente.

Comportamento recomendado:

- Adicionar botao `Entrar com Google`.
- Usar Google OAuth/OpenID Connect.
- Exigir variaveis de ambiente para client id e client secret.
- Criar ou vincular usuario local por e-mail Google verificado.
- Armazenar dados do provedor separadamente quando possivel.
- Manter login tradicional por e-mail/senha funcionando.

Campos opcionais em `usuarios`:

- `auth_provider`
- `google_sub`
- `email_verificado`

Tabela alternativa recomendada para multiplos provedores:

```sql
user_identities (
    id,
    user_id,
    provider,
    provider_user_id,
    email,
    criado_em
)
```

Requisitos de seguranca:

- Nao armazenar access tokens do Google se nao for necessario.
- Proteger client secret por variaveis de ambiente.
- Validar parametro OAuth `state`.
- Validar redirect URI.
- Nao quebrar login existente por e-mail/senha.
- Nao versionar credenciais OAuth.

Criterios de aceite:

- [ ] Usuario consegue entrar com Google.
- [ ] Conta local e criada ou vinculada com seguranca.
- [ ] Segredos OAuth nao sao commitados.
- [ ] Login existente por e-mail/senha continua funcionando.
- [ ] E-mail retornado pelo Google e tratado como verificado apenas quando o provedor indicar essa informacao.

### Phase 12 - P3 - Melhorias Futuras Opcionais

Objetivo: registrar ideias sem transformar tudo em prioridade imediata.

Ideias:

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
- `email_verificado BOOLEAN DEFAULT false`
- `email_verificado_em TIMESTAMP NULL`
- `auth_provider` Opcional
- `google_sub` Opcional

Observacoes:

- Senha deve ser sempre hash.
- E-mail ativo deve ser unico.
- Desativacao deve usar soft delete.
- `auth_provider` e `google_sub` devem ser usados apenas se a estrategia escolhida nao usar tabela separada de identidades.

#### `email_verification_tokens` Opcional

Uso: verificar controle do e-mail informado pelo usuario.

Campos sugeridos:

- `id`
- `user_id`
- `token_hash`
- `criado_em`
- `expira_em`
- `usado_em`

Observacoes:

- Nao armazenar token puro.
- Nao registrar token em logs.
- Token deve expirar e ser de uso unico.

#### `password_reset_tokens` Opcional

Uso: redefinicao segura de senha por e-mail.

Campos sugeridos:

- `id`
- `user_id`
- `token_hash`
- `criado_em`
- `expira_em`
- `usado_em`

Observacoes:

- Mensagens publicas devem ser neutras.
- Nao revelar se o e-mail existe.
- Nova senha deve ser salva apenas como hash.

#### `user_identities` Opcional

Uso: vincular usuarios locais a provedores externos como Google.

Campos sugeridos:

- `id`
- `user_id`
- `provider`
- `provider_user_id`
- `email`
- `criado_em`

Observacoes:

- Evita sobrecarregar a tabela `usuarios` com campos especificos de cada provedor.
- Facilita adicionar outros provedores no futuro.
- Nao armazenar access tokens se nao for necessario.

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
- Qual servico de e-mail sera usado: SMTP proprio, SendGrid, Gmail app password ou outro provedor?
- A verificacao de e-mail sera obrigatoria antes de usar o Chat IA?
- Usuarios nao verificados devem ser bloqueados ou apenas avisados?
- Quem pode reativar uma conta desativada?
- Exclusao fisica sera exigida por alguma politica ou soft delete sera suficiente?
- Onde as credenciais do Google OAuth serao configuradas em ambientes local e servidor?
- Google login deve ser permitido para qualquer dominio de e-mail ou apenas dominios autorizados?

## 6. Recomendacoes Imediatas

Proximas 3 tarefas recomendadas, em ordem:

1. Finalizar estabilizacao da autenticacao e validar o fluxo completo em ambiente local, Docker e servidor.
2. Padronizar soft delete de usuarios com `deletado BOOLEAN DEFAULT false` e, se aprovado, `deletado_em TIMESTAMP NULL`.
3. Planejar o servico de e-mail antes de implementar verificacao de e-mail ou recuperacao de senha.

## 7. Definicao de Pronto Geral

Um incremento deve ser considerado pronto quando:

- Mantem `Estatisticas` publica.
- Mantem `Chat IA` protegido.
- Nao altera dados analiticos DATASUS por fluxos de usuario.
- Nao expõe credenciais, tokens, senhas, hashes ou tracebacks na UI.
- Possui testes ou verificacao manual documentada.
- Possui logs tecnicos seguros para diagnostico.
- Preserva o papel do Power BI como painel visual consolidado.

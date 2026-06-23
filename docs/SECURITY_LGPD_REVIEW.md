# Revisao LGPD e Seguranca - SIA/DATASUS

Atualizado em: 2026-06-22

Este documento registra decisoes e cuidados de seguranca e privacidade para o app SIA/DATASUS. Ele apoia a revisao tecnica do projeto, mas nao substitui uma avaliacao juridica formal de LGPD.

## Objetivo

O objetivo desta revisao e documentar:

- quais dados pessoais e operacionais o app armazena;
- por que esses dados sao armazenados;
- como autenticacao, tokens, historico de chat e diagnosticos sao protegidos;
- como os dados analiticos DATASUS permanecem separados e tratados como somente leitura;
- quais riscos e pendencias ainda precisam de decisao da equipe.

## Dados Pessoais Armazenados

### Tabela `usuarios`

A tabela `usuarios` pertence ao dominio da aplicacao, nao ao dominio analitico DATASUS. Ela pode armazenar:

- `id`: identificador interno do usuario.
- `nome`: nome exibido no perfil e na interface.
- `email`: identificador de login e contato.
- `senha_hash`: hash da senha, nunca a senha em texto puro.
- `role`: papel/perfil tecnico do usuario, quando usado.
- `criado_em`: data de criacao da conta.
- `atualizado_em`: data da ultima atualizacao cadastral.
- `ultimo_login_em`: data do ultimo login.
- `deletado`: flag de soft delete/desativacao.
- `deletado_em`: data de desativacao da conta.
- `email_verificado`: indica se o controle do e-mail foi confirmado.
- `email_verificado_em`: data de verificacao do e-mail.

### Tabela `email_verification_tokens`

Usada para a fundacao de verificacao de e-mail. Pode armazenar:

- `id`;
- `user_id`;
- `token_hash`;
- `criado_em`;
- `expira_em`;
- `usado_em`.

Regras:

- O token cru nao deve ser armazenado.
- Apenas `token_hash` deve ser persistido.
- O token deve expirar.
- O token deve ser de uso unico.
- O token cru nao deve aparecer em logs, diagnosticos ou interface.

### Tabela `pending_email_changes`

Usada para confirmar alteracao do e-mail da conta por codigo enviado ao novo endereco. Pode armazenar:

- `id`;
- `user_id`;
- `novo_email`;
- `codigo_hash`;
- `criado_em`;
- `expira_em`;
- `usado_em`.
- `tentativas`.

Regras:

- O e-mail em `usuarios.email` nao deve ser alterado antes da confirmacao valida do codigo enviado ao novo endereco.
- O codigo cru nao deve ser armazenado.
- Apenas `codigo_hash` deve ser persistido.
- O codigo deve expirar.
- O codigo deve ter limite de tentativas.
- O codigo deve ser de uso unico.
- O codigo cru nao deve aparecer em logs, diagnosticos ou interface.

### Tabela `pending_registrations`

Usada pelo cadastro com confirmacao por codigo antes da criacao da conta real em `usuarios`. Pode armazenar:

- `id`;
- `nome`;
- `email`;
- `senha_hash`;
- `codigo_hash`;
- `criado_em`;
- `expira_em`;
- `usado_em`;
- `tentativas`;
- `consumed_user_id`.

Regras:

- A conta real nao deve ser criada em `usuarios` antes da confirmacao valida do codigo.
- A senha temporaria deve ser armazenada apenas como `senha_hash`.
- O codigo deve ser armazenado apenas como `codigo_hash`.
- O codigo deve expirar.
- O codigo deve ter limite de tentativas.
- O cadastro pendente deve ser de uso unico.
- Codigo cru, senha em texto puro e hash de senha nao devem aparecer em logs, diagnosticos ou interface.

### Tabela `password_reset_tokens`

Usada para a fundacao de recuperacao de senha por e-mail. Pode armazenar:

- `id`;
- `user_id`;
- `token_hash`;
- `criado_em`;
- `expira_em`;
- `usado_em`.

Regras:

- O token cru nao deve ser armazenado.
- Apenas `token_hash` deve ser persistido.
- O token deve expirar.
- O token deve ser de uso unico.
- O token cru e o link completo de recuperacao nao devem aparecer em logs, diagnosticos ou interface.

### Tabela `account_reactivation_tokens`

Usada para reativar contas desativadas por soft delete quando o usuario comprova controle do e-mail. Pode armazenar:

- `id`;
- `user_id`;
- `codigo_hash`;
- `criado_em`;
- `expira_em`;
- `usado_em`;
- `tentativas`.

Regras:

- Conta desativada nao deve ser recriada como novo usuario.
- Reativacao deve exigir confirmacao por codigo enviado ao e-mail da conta.
- Apenas `codigo_hash` deve ser persistido.
- Codigo cru nao deve aparecer em logs, diagnosticos ou interface.
- Codigo deve expirar, ter limite de tentativas e ser de uso unico.
- Reativacao automatica deve respeitar a janela configurada por `ACCOUNT_REACTIVATION_WINDOW_DAYS`.
- Contas antigas fora da janela devem exigir decisao administrativa futura, nao reativacao automatica.

## Finalidade dos Dados

- `nome`: exibir identificacao amigavel no perfil e na sessao.
- `email`: autenticar usuario, identificar conta, apoiar verificacao de e-mail e futuras notificacoes.
- `senha_hash`: validar senha sem armazenar senha em texto puro.
- `role`: permitir controle futuro de permissoes, se necessario.
- `criado_em` e `atualizado_em`: apoiar auditoria basica e suporte.
- `ultimo_login_em`: apoiar auditoria basica de acesso.
- `deletado` e `deletado_em`: permitir desativacao segura sem exclusao fisica imediata.
- `email_verificado` e `email_verificado_em`: registrar se o usuario confirmou controle do e-mail.
- `pending_email_changes`: permitir alterar o e-mail da conta somente depois de confirmacao por codigo enviado ao novo endereco.
- `pending_registrations`: permitir confirmar o e-mail por codigo antes de criar a conta real.
- `email_verification_tokens`: permitir verificacao segura de e-mail em fluxos de perfil ou evolucoes futuras.
- `password_reset_tokens`: permitir recuperacao segura de senha.
- `account_reactivation_tokens`: permitir reativacao segura de conta desativada com prova de controle do e-mail.
- `chat_sessions` e `chat_messages`: armazenar historico autenticado do Chat IA e apoiar auditabilidade.

## Dados do Chat IA

O historico do Chat IA pertence ao dominio da aplicacao e deve ficar separado dos dados DATASUS.

### `chat_sessions`

Agrupa conversas de um usuario autenticado. Cada sessao deve estar associada a `user_id`.

Campos esperados:

- `id`;
- `user_id`;
- `titulo`;
- `criado_em`;
- `atualizado_em`;
- `deletado`;
- `deletado_em`.

### `chat_messages`

Armazena mensagens da conversa. Cada mensagem deve estar associada a `chat_session_id` e `user_id`.

Campos esperados:

- `id`;
- `chat_session_id`;
- `user_id`;
- `role`;
- `conteudo`;
- `status`;
- `criado_em`;
- `deletado`;
- `deletado_em`.

Regras:

- Historico deve usar soft delete quando o usuario ocultar/remover conversa.
- Mensagens devem ficar associadas ao usuario autenticado.
- Conteudo sensivel nao deve ser armazenado intencionalmente.
- Tokens, links sensiveis, senhas, hashes e chaves obvias devem ser redigidos antes da persistencia quando detectados.
- Erros brutos de provedor, tracebacks e strings de conexao nao devem ser persistidos como resposta exibida ao usuario.
- Status seguros como `ok`, `blocked`, `error` ou `fallback` podem apoiar auditoria sem expor detalhes sensiveis.

## Dados DATASUS

Os dados DATASUS pertencem ao dominio analitico e devem permanecer separados das tabelas de aplicacao.

Estruturas analiticas:

- `data_sus`;
- `dim_*`;
- `vw_data_sus_ia`.

Regras:

- Autenticacao, e-mail, recuperacao de senha, perfil e historico de chat nao devem ser armazenados em `data_sus`, `dim_*` ou `vw_data_sus_ia`.
- A view `vw_data_sus_ia` e a fonte analitica enriquecida usada pelo Chat IA.
- A aplicacao deve tratar `vw_data_sus_ia` como fonte somente leitura.
- Fluxos de usuario nao devem executar `INSERT`, `UPDATE`, `DELETE`, `DROP`, `ALTER` ou `CREATE` sobre dados analiticos DATASUS.
- O usuario de banco usado pela camada de IA deve seguir o principio do menor privilegio, preferencialmente com permissao apenas de `SELECT` na view necessaria.

## Protecoes Implementadas

- Senhas sao armazenadas como hash, nao em texto puro.
- Fluxos normais de remocao usam soft delete com `deletado` e `deletado_em`.
- Login bloqueia usuarios desativados/deletados.
- Tokens de verificacao de e-mail e recuperacao de senha usam `token_hash`.
- Alteracao de e-mail exige senha atual e codigo enviado ao novo endereco antes de modificar `usuarios.email`.
- Alteracoes pendentes de e-mail armazenam `codigo_hash`, nunca codigo em texto puro.
- Confirmacao valida de alteracao de e-mail marca `email_verificado = true` e preenche `email_verificado_em`.
- O cadastro por e-mail usa `pending_registrations` e so cria usuario apos codigo valido.
- Cadastros pendentes armazenam `senha_hash` e `codigo_hash`, nunca senha ou codigo em texto puro.
- Tokens possuem expiracao.
- Tokens sao de uso unico.
- Codigos de cadastro possuem expiracao, limite de tentativas e uso unico.
- Reativacao de conta desativada exige codigo por e-mail, usa `codigo_hash` e respeita janela configuravel.
- Contas desativadas nao sao recriadas silenciosamente no cadastro.
- Mensagens publicas do cadastro sao neutras para evitar enumeracao de contas.
- O estado real da conta (nova conta ou reativacao) so deve ser informado depois que o usuario confirma o codigo enviado ao e-mail.
- Recuperacao de senha usa mensagem publica neutra:

> Se houver uma conta com este e-mail, enviaremos instrucoes de recuperacao.

- O modo de e-mail fake/local e o padrao enquanto envio real nao estiver configurado.
- O sistema nao deve prometer envio real de e-mail quando `EMAIL_ENABLED=false`.
- Health checks e diagnosticos sanitizam segredos e mostram apenas status seguro.
- A interface deve evitar tracebacks, tokens, senhas, hashes, API keys e strings de conexao.
- O Chat IA bloqueia prompts perigosos ou fora de escopo quando detectados.
- O Chat IA usa handlers/fallbacks estatisticos controlados quando possivel.
- A camada de IA nao deve executar SQL arbitrario gerado diretamente do prompt do usuario.
- A view `vw_data_sus_ia` e consultada apenas como fonte de leitura para analises.

## Segredos e Variaveis de Ambiente

Os seguintes segredos nunca devem ser commitados:

- `GEMINI_API_KEY`;
- `OPENROUTER_API_KEY`;
- `OPENAI_API_KEY`;
- `AI_LLM_API_KEY`;
- `AI_DB_PASSWORD`;
- `EMAIL_SMTP_PASSWORD`;
- `EMAIL_API_KEY`;
- futuros OAuth client secrets;
- strings de conexao de banco com usuario e senha.

Regras:

- Segredos devem ser configurados no ambiente do servidor, portal de deploy ou GitHub Secrets quando apropriado.
- Arquivos `.env` reais nao devem ser versionados.
- Logs e diagnosticos devem mostrar apenas status como `api_key_configured: true/false`.
- Logs nao devem exibir valores de chave, senha, token, codigo, hash, link de reset ou string de conexao completa.
- Mensagens de erro exibidas na interface devem ser amigaveis e sem detalhes tecnicos sensiveis.

## Retencao, Desativacao e Exclusao

O fluxo normal visivel para usuario deve ser `Desativar conta`, nao exclusao fisica.

Comportamento esperado:

- Definir `deletado = true`.
- Definir `deletado_em` com timestamp quando disponivel.
- Encerrar a sessao autenticada.
- Bloquear novos logins da conta desativada.
- Ocultar usuarios desativados de listagens normais.
- Nao usar `DELETE FROM usuarios` no fluxo normal.

Reativacao segura:

- Conta desativada pode ser reativada somente com prova de controle do e-mail.
- A reativacao usa codigo com hash, expiracao, limite de tentativas e uso unico.
- A tela publica de cadastro nao deve informar que a conta esta ativa, desativada, inexistente ou fora da janela.
- Antes da confirmacao por codigo, usar mensagem neutra como: `Se for possivel continuar com este e-mail, enviaremos instrucoes para ele.`
- Depois de codigo valido, a interface pode informar se a conta foi criada ou reativada, pois o usuario provou controle do e-mail.
- A janela padrao de reativacao automatica e controlada por `ACCOUNT_REACTIVATION_WINDOW_DAYS`.
- Contas fora da janela nao devem ser reativadas automaticamente.
- Reativacao limpa `deletado`, `deletado_em` e `deleted_at` quando existir, sem criar outro usuario.

Exclusao fisica definitiva, expurgo ou remocao administrativa so deve existir futuramente se houver:

- politica explicita;
- autorizacao clara;
- confirmacao forte;
- trilha de auditoria;
- avaliacao de impacto sobre historico, auditoria e obrigacoes legais.

## Riscos e Pontos Pendentes

- Envio real por SMTP/API ainda nao esta configurado por padrao.
- Verificacao de e-mail nao e obrigatoria por padrao.
- Google OAuth ainda nao foi implementado.
- Papeis e permissoes administrativas para diagnosticos ainda nao estao finalizados.
- Periodo de retencao do historico de chat ainda nao foi formalmente definido.
- Politica de expurgo/exclusao fisica ainda nao foi definida.
- Revisao juridica/LGPD de producao ainda sera necessaria.
- Politica de reativacao de conta desativada ainda precisa ser definida.
- A janela de reativacao automatica pode precisar de validacao da equipe/professor.
- Politica para acesso administrativo a historico de chat ainda precisa ser definida.
- A equipe ainda precisa confirmar o provedor real de e-mail e a gestao de segredos no servidor.

## Checklist de Seguranca

- [ ] Nenhum `.env` real foi commitado.
- [ ] Nenhuma API key foi commitada.
- [ ] Nenhum token cru e registrado em logs.
- [ ] Nenhum codigo de cadastro cru e registrado em logs.
- [ ] Nenhum link completo de verificacao ou recuperacao com token e registrado em logs.
- [ ] Nenhum codigo de alteracao de e-mail cru e registrado em logs.
- [ ] Nenhuma senha e registrada em logs.
- [ ] Nenhum hash de senha aparece na interface.
- [ ] Nenhum traceback aparece na interface.
- [ ] `Chat IA` permanece protegido por login.
- [ ] `Estatisticas` permanece publica.
- [ ] Cadastro nao revela se o e-mail pertence a conta ativa, desativada ou inexistente.
- [ ] Estado de conta so e revelado apos confirmacao de codigo enviado ao e-mail.
- [ ] Dados analiticos DATASUS permanecem somente leitura para o app.
- [ ] Desativacao de usuario usa soft delete.
- [ ] Reativacao de usuario exige confirmacao por e-mail.
- [ ] Alteracao de e-mail exige codigo enviado ao novo endereco.
- [ ] Recuperacao de senha usa mensagem neutra.
- [ ] Cadastro cria usuario apenas depois da confirmacao do codigo de e-mail.
- [ ] Health checks nao expoem segredos.
- [ ] Diagnosticos mostram chaves apenas como booleano configurado/ausente.
- [ ] Logs tecnicos usam causas seguras e nao payloads sensiveis.
- [ ] Tabelas de aplicacao ficam separadas de `data_sus`, `dim_*` e `vw_data_sus_ia`.

## Observacao Final

Esta revisao deve ser atualizada sempre que o projeto adicionar:

- envio real de e-mail;
- verificacao obrigatoria de e-mail;
- Google OAuth;
- novas permissoes administrativas;
- exportacao de arquivos;
- retencao formal de historico;
- integracoes externas com dados pessoais.

# Plano de Servico de E-mail - SIA/DATASUS

Atualizado em: 2026-06-22

Este documento planeja a estrategia de envio de e-mails para funcionalidades de autenticacao. A fundacao interna de e-mail, a fundacao de verificacao de e-mail e a fundacao de recuperacao de senha ja existem em modo seguro/fake por padrao. O envio real por SMTP esta disponivel quando explicitamente habilitado por variaveis de ambiente. Google login e envio por provedores de API continuam fora do escopo atual.

## Objetivo

O servico de e-mail devera apoiar, em fases futuras:

- Verificar que o usuario controla o e-mail cadastrado.
- Enviar codigo de verificacao para confirmar o e-mail antes de criar a conta.
- Enviar links de confirmacao para alterar o e-mail da conta somente depois que o usuario provar controle do novo endereco.
- Enviar links de recuperacao de senha.
- Enviar notificacoes de seguranca, se o projeto precisar disso depois.
- Evitar comportamento falso ou enganoso, como dizer que um e-mail real foi enviado quando o ambiente ainda esta em modo local, fake ou sem configuracao.

O objetivo imediato e manter uma estrategia segura para evoluir verificacao de e-mail e recuperacao de senha sem prometer envio real antes da configuracao do provedor.

## Servicos Possiveis

### Opcao A - SMTP

Uso de um servidor SMTP generico, como o SMTP institucional, do provedor de hospedagem ou de outro servico autorizado.

Vantagens:

- E facil de entender e explicar em contexto academico.
- Usa um padrao conhecido e bem documentado.
- Pode funcionar com varios provedores sem prender o projeto a uma API especifica.

Pontos de atencao:

- Depende de credenciais do provedor.
- Alguns provedores bloqueiam ou limitam SMTP em ambientes de servidor.
- Pode exigir TLS, portas especificas e liberacao na infraestrutura.
- A entrega e o monitoramento podem ser mais simples ou mais limitados que em provedores especializados.

### Opcao B - Gmail app password

Uso de uma conta Gmail com 2FA habilitado e senha de app.

Vantagens:

- Pode ser util para prototipo academico ou demonstracao rapida.
- E relativamente facil de configurar quando a conta permite senha de app.
- Nao exige dominio proprio no inicio.

Pontos de atencao:

- Nao e ideal para producao.
- Exige 2FA e criacao de senha de app.
- Pode sofrer limites de envio.
- A senha de app nunca deve ser commitada.
- A conta usada precisa ser institucional/projeto, nao uma conta pessoal sem politica clara.

### Opcao C - SendGrid, Mailgun, Resend ou provedor similar por API

Uso de um provedor especializado com API HTTP e chave de acesso.

Vantagens:

- Melhor para uma entrega mais parecida com producao.
- Normalmente tem dashboard de entregas, falhas e reputacao.
- Pode facilitar templates, logs de envio e monitoramento.
- Geralmente evita problemas de porta SMTP bloqueada.

Pontos de atencao:

- Requer API key.
- Pode exigir verificacao de dominio.
- Pode ter custo ou limites no plano gratuito.
- Nao deve ser escolhido automaticamente sem aprovacao da equipe.
- A chave de API nunca deve ser commitada.

## Recomendacao Inicial

Para este projeto academico, a recomendacao e:

1. Criar primeiro uma abstracao interna de e-mail, por exemplo `EmailService`, em fase futura.
2. Suportar um modo `fake`, `local` ou `dev` que nao envia e-mail real.
3. No modo local, registrar apenas metadados seguros, como tipo de evento, destinatario mascarado e status simulado.
4. Nunca registrar token, link completo, senha, hash, API key ou credencial SMTP.
5. Suportar modo real via SMTP usando variaveis de ambiente.
6. Nunca mostrar ao usuario que um e-mail real foi enviado quando o sistema estiver em modo fake/local.

Recomendacao pratica para a primeira implementacao futura:

- `EMAIL_ENABLED=false` por padrao.
- `EMAIL_PROVIDER=fake` em desenvolvimento/local.
- SMTP apenas quando a equipe tiver credenciais e URL publica configuradas.
- Provedores por API podem ser adicionados em etapa futura.
- Mensagens da interface devem diferenciar modo real e modo ainda nao configurado quando isso for necessario para evitar promessa falsa.

Implementacao inicial disponivel:

- Modulo: `src/auth/email_service.py`.
- Classe principal: `EmailService`.
- Resultado estruturado: `EmailSendResult`.
- Modo fake/local funcional por padrao.
- SMTP envia e-mail real quando `EMAIL_ENABLED=true`, `EMAIL_PROVIDER=smtp` e a configuracao esta completa.
- Provedores por API ficam preparados por configuracao, mas ainda nao enviam e-mail real.
- Fundacao de verificacao: `src/auth/email_verification_service.py`.
- Tabela de tokens: `email_verification_tokens`, armazenando somente `token_hash`.
- Campos de usuario: `email_verificado` e `email_verificado_em`.
- Controle de exigencia: `EMAIL_VERIFICATION_REQUIRED=false` por padrao, para nao bloquear login ou Chat IA enquanto o envio real nao estiver configurado.
- Se `EMAIL_VERIFICATION_REQUIRED=true`, o usuario ainda pode fazer login e acessar o perfil, mas o Chat IA fica bloqueado ate a verificacao do e-mail.
- Cadastro com confirmacao por codigo: `src/auth/pending_registration_service.py`.
- Tabela temporaria: `pending_registrations`, armazenando `senha_hash` e `codigo_hash`, nunca senha ou codigo em texto puro.
- O usuario so e criado em `usuarios` depois que o codigo enviado por e-mail e confirmado.
- Em modo fake/local (`EMAIL_ENABLED=false`), o cadastro nao e concluido e a interface informa que o envio de e-mail ainda nao esta configurado.
- Reativacao de conta desativada: `src/auth/account_reactivation_service.py`.
- Tabela de reativacao: `account_reactivation_tokens`, armazenando apenas `codigo_hash`.
- Janela configuravel: `ACCOUNT_REACTIVATION_WINDOW_DAYS`, padrao de 90 dias.
- Contas desativadas nao sao recriadas silenciosamente; a reativacao exige confirmacao por e-mail.
- Fundacao de recuperacao de senha: `src/auth/password_reset_service.py`.
- Tabela de tokens: `password_reset_tokens`, armazenando somente `token_hash`.
- Mensagem publica neutra: `Se houver uma conta com este e-mail, enviaremos instrucoes de recuperacao.`
- Alteracao verificada de e-mail: `src/auth/email_change_service.py`.
- Tabela de tokens: `email_change_tokens`, armazenando somente `token_hash` e o novo e-mail solicitado.
- O e-mail em `usuarios.email` so e atualizado depois que o link enviado ao novo endereco e confirmado.

Exemplo de comportamento seguro em modo fake/local:

- Cadastro: informar que o envio de e-mail ainda nao esta configurado e nao criar a conta.
- Reativacao: informar que o envio de e-mail ainda nao esta configurado e nao reativar a conta.
- Recuperacao de senha: usar mensagem neutra sem prometer envio real quando o ambiente estiver em modo fake/local.

## Variaveis de Ambiente Sugeridas

Configuracao comum:

```env
EMAIL_ENABLED=false
EMAIL_PROVIDER=fake
EMAIL_FROM=
APP_PUBLIC_URL=
APP_PUBLIC_BASE_URL=
EMAIL_PUBLIC_BASE_URL=
ACCOUNT_REACTIVATION_WINDOW_DAYS=90
```

Configuracao SMTP:

```env
EMAIL_PROVIDER=smtp
EMAIL_ENABLED=true
EMAIL_FROM=
EMAIL_SMTP_HOST=
EMAIL_SMTP_PORT=
EMAIL_SMTP_USERNAME=
EMAIL_SMTP_PASSWORD=
EMAIL_USE_TLS=true
```

Configuracao por provedor de API:

```env
EMAIL_PROVIDER=resend
EMAIL_API_KEY=
EMAIL_FROM=
```

Observacoes:

- Segredos devem ser configurados no ambiente do servidor, portal da disciplina ou GitHub Secrets quando fizer sentido.
- Nenhuma senha SMTP, API key, token ou segredo deve ser versionado no repositorio.
- `APP_PUBLIC_BASE_URL`, `EMAIL_PUBLIC_BASE_URL` ou `APP_PUBLIC_URL` sera necessario para montar links de alteracao de e-mail, verificacao e recuperacao em ambiente real.
- Se nenhuma URL publica for configurada, o fallback local e `http://localhost:8501`.
- Em ambiente local sem URL publica, deve-se usar modo fake/local ou uma URL explicitamente configurada para teste.

Exemplo local para Gmail SMTP, sem credenciais reais:

```env
EMAIL_ENABLED=true
EMAIL_PROVIDER=smtp
EMAIL_SMTP_HOST=smtp.gmail.com
EMAIL_SMTP_PORT=587
EMAIL_USE_TLS=true
EMAIL_SMTP_USERNAME=remetente-do-projeto@gmail.com
EMAIL_SMTP_PASSWORD=senha-de-app-do-google
EMAIL_FROM="SIA DATASUS <remetente-do-projeto@gmail.com>"
APP_PUBLIC_BASE_URL=http://localhost:8501
```

Para servidor, use a URL publica do ambiente:

```env
APP_PUBLIC_BASE_URL=https://eq10.dsc.rodrigor.com
```

Nunca commitar esses valores reais. Configure credenciais no ambiente do servidor, portal de deploy ou GitHub Secrets quando apropriado.

## Seguranca

Regras obrigatorias para as fases futuras:

- Nunca registrar tokens de verificacao.
- Nunca registrar links completos de alteracao de e-mail, recuperacao ou verificacao.
- Nunca registrar credenciais SMTP.
- Nunca registrar API keys.
- Nunca registrar senhas ou hashes.
- Armazenar hash do token, nao o token bruto, sempre que possivel.
- Token deve expirar.
- Token deve ser de uso unico.
- Token usado deve ser marcado com `usado_em` ou equivalente.
- Mensagens publicas nao devem revelar se um e-mail existe no sistema.
- Alteracao de e-mail deve exigir senha atual e confirmacao pelo novo endereco antes de modificar `usuarios.email`.
- O fluxo de recuperacao deve usar mensagem neutra:

> Se houver uma conta com este e-mail, enviaremos instrucoes de recuperacao.

Tambem e recomendado:

- Mascarar e-mails em logs, por exemplo `a***@dominio.com`.
- Separar logs de auditoria de mensagens exibidas ao usuario.
- Garantir que erros de SMTP/API nao mostrem credenciais ou payloads sensiveis na interface.
- Usar tempo de expiracao curto para tokens de recuperacao.

## Integracao com Verificacao de E-mail

Fluxo de cadastro implementado:

- O formulario de cadastro coleta nome, e-mail, senha e confirmacao.
- Antes de criar usuario em `usuarios`, o sistema cria um registro temporario em `pending_registrations`.
- `pending_registrations` armazena `senha_hash`, nunca senha em texto puro.
- O codigo de verificacao e numerico, curto, gerado com fonte segura e armazenado apenas como `codigo_hash`.
- O codigo expira e possui limite de tentativas.
- O codigo e de uso unico; depois de confirmado, `usado_em` e preenchido.
- Somente depois da confirmacao valida o usuario real e criado em `usuarios`.
- O usuario criado recebe `email_verificado = true`, `email_verificado_em` preenchido e `deletado = false`.
- Em modo fake/local, o sistema nao finge envio real e nao conclui o cadastro.
- E-mails duplicados ativos sao bloqueados antes de criar cadastro pendente.
- E-mails de usuarios desativados (`deletado = true`) nao sao recriados silenciosamente.

Fluxo completo em ambiente com envio real:

1. Usuario preenche o cadastro.
2. Sistema valida os campos e verifica duplicidade de e-mail ativo.
3. Sistema cria `pending_registrations` com `senha_hash` e `codigo_hash`.
4. Sistema envia o codigo por e-mail.
5. Modal muda para `Confirme seu e-mail`.
6. Usuario informa o codigo.
7. Sistema valida hash, expiracao, tentativas e uso unico.
8. Sistema cria a conta real em `usuarios`.
9. Sistema marca `email_verificado = true` e preenche `email_verificado_em`.
10. Sistema marca o cadastro pendente como usado.

A fundacao anterior por token/link (`email_verification_tokens`) permanece disponivel para verificacao/reenvio de e-mail em fluxos de perfil ou evolucoes futuras, mas o cadastro novo usa codigo antes de criar a conta.

## Integracao com Reativacao de Conta

Fluxo implementado:

- O cadastro usa mensagem publica neutra para evitar enumeracao de contas.
- A interface nao deve revelar se o e-mail pertence a conta ativa, conta desativada, cadastro pendente ou nenhuma conta.
- Se o cadastro encontra uma conta ativa com o e-mail informado, o cadastro continua bloqueado internamente e nao cria novo usuario.
- Se o cadastro encontra uma conta desativada (`deletado = true`), o sistema nao cria novo usuario.
- Dentro da janela permitida, o sistema cria um codigo de reativacao, armazena apenas `codigo_hash` e envia o codigo por e-mail.
- O codigo expira, tem limite de tentativas e e de uso unico.
- A reativacao so e permitida dentro de `ACCOUNT_REACTIVATION_WINDOW_DAYS`, com padrao de 90 dias.
- Se `deletado_em` estiver ausente, a conta e tratada como desativada sem quebrar o fluxo.
- Se a conta estiver fora da janela, a interface publica continua neutra; detalhes ficam restritos ao fluxo interno/log seguro.
- Em modo fake/local, o sistema nao finge envio real e nao reativa a conta.
- Ao confirmar codigo valido, o sistema define `deletado = false`, limpa `deletado_em` e `deleted_at` quando existir, atualiza `atualizado_em` e marca o e-mail como verificado.

Mensagem publica recomendada para solicitacao de cadastro/reativacao:

> Se for possivel continuar com este e-mail, enviaremos instrucoes para ele.

Essa abordagem evita enumeracao de contas. O estado real so deve aparecer depois da confirmacao do codigo enviado ao e-mail, quando o usuario ja provou controle do endereco.

## Integracao com Recuperacao de Senha

Fundacao implementada:

- Solicitar recuperacao sem revelar se o e-mail existe.
- Criar token somente para usuario ativo e nao deletado.
- Armazenar apenas o hash SHA-256 do token.
- Definir expiracao curta.
- Bloquear token expirado ou ja usado.
- Marcar token usado com `usado_em` depois da redefinicao.
- Salvar nova senha apenas como hash.
- Remover o token da URL quando o app recebe `reset_password_token`.
- Usar o `EmailService` em modo fake/local por padrao sem prometer envio real.
- Enviar e-mail real por SMTP quando `EMAIL_ENABLED=true` e `EMAIL_PROVIDER=smtp`.
- Links de recuperacao usam `APP_PUBLIC_BASE_URL`, `EMAIL_PUBLIC_BASE_URL`, `APP_PUBLIC_URL` ou fallback local.
- O link deve apontar para a raiz publica do app com `?reset_password_token=<token>`, sem parametros extras como `?page=estatisticas`.

Fluxo completo em ambiente com envio real:

1. Usuario clica em `Esqueci minha senha`.
2. Usuario informa o e-mail.
3. UI sempre mostra mensagem neutra, mesmo se a conta nao existir.
4. Se a conta existir e estiver ativa, o sistema cria token de recuperacao.
5. Sistema armazena apenas o hash do token.
6. Sistema define expiracao curta.
7. Sistema envia link de recuperacao por e-mail se o envio real estiver configurado.
8. Usuario abre o link.
9. Usuario define nova senha.
10. Sistema valida token, expiracao e uso unico.
11. Sistema salva a nova senha apenas como hash.
12. Token e marcado como usado.

Regras:

- Nao criar token para usuario desativado.
- Nao revelar se o e-mail existe.
- Nao reutilizar token.
- Nao aceitar token expirado.
- Nao armazenar senha em texto puro.

## Integracao com Alteracao Verificada de E-mail

Fluxo implementado:

- Usuario acessa `Meu perfil` e escolhe `Alterar e-mail`.
- O formulario solicita o novo e-mail e a senha atual.
- O sistema valida formato, e-mail diferente do atual, senha atual e duplicidade de e-mail ativo.
- O sistema nao altera `usuarios.email` imediatamente.
- O sistema cria um registro em `email_change_tokens` com `novo_email`, `token_hash`, `criado_em`, `expira_em` e `usado_em`.
- O token cru existe apenas para montar o link enviado por e-mail e nao deve ser registrado em logs.
- O link usa `?confirm_email_change_token=<token>`.
- Quando o usuario abre o link, o app valida token, expiracao, uso unico e duplicidade.
- Somente depois da confirmacao valida o sistema atualiza `usuarios.email`, define `email_verificado = true`, preenche `email_verificado_em` e atualiza `atualizado_em`.
- O token e marcado como usado.
- Se o usuario ainda estiver logado no mesmo navegador, a sessao e atualizada com o novo e-mail.

Mensagens esperadas:

- Envio real bem-sucedido: `Enviamos um link de confirmacao para o novo e-mail.`
- Envio desabilitado/fake: `O envio de e-mail ainda nao esta configurado. Nao foi possivel alterar o e-mail agora.`
- Link valido: `E-mail alterado com sucesso.`
- Link invalido, expirado ou ja usado: mensagem segura sem expor token ou detalhes internos.

Regras:

- Nao atualizar o e-mail antes da confirmacao pelo novo endereco.
- Nao expor se o novo e-mail pertence a outro usuario alem da mensagem segura `Nao foi possivel usar este e-mail.`
- Nao registrar token cru, link completo, senha atual, senha SMTP ou API key.
- Em modo fake/local, nao fingir que o link real foi enviado.

## Notificacoes Futuras de Seguranca

Depois que o envio real estiver funcionando, o mesmo servico pode apoiar notificacoes como:

- Senha alterada.
- E-mail alterado ou solicitacao de alteracao de e-mail.
- Login suspeito, se houver criterio tecnico confiavel.
- Conta desativada.

Essas notificacoes devem ser simples, sem incluir tokens, senhas, hashes ou dados analiticos DATASUS.

## Teste Manual de SMTP

Passos recomendados para testar envio real sem commitar segredos:

1. Criar ou escolher um e-mail remetente dedicado ao projeto.
2. Se usar Gmail, ativar verificacao em duas etapas na conta.
3. Criar uma senha de app do Google para SMTP.
4. Configurar as variaveis `EMAIL_ENABLED=true`, `EMAIL_PROVIDER=smtp`, `EMAIL_SMTP_HOST`, `EMAIL_SMTP_PORT`, `EMAIL_SMTP_USERNAME`, `EMAIL_SMTP_PASSWORD`, `EMAIL_FROM`, `EMAIL_USE_TLS=true` e `APP_PUBLIC_BASE_URL`.
5. Rodar o app Streamlit no ambiente desejado.
6. Criar uma nova conta e verificar se o e-mail com codigo de cadastro chegou.
7. Digitar o codigo no app e confirmar que a conta so e criada depois da validacao.
8. Usar `Esqueci minha senha` e confirmar que o e-mail de recuperacao chegou.
9. Abrir o link de recuperacao, definir uma nova senha e confirmar que a senha antiga deixa de funcionar.
10. Conferir logs e interface para garantir que senha SMTP, codigo de cadastro, tokens e URLs completas com token nao aparecem.

## Decisoes Pendentes

- Qual provedor a equipe usara: SMTP, Gmail app password, SendGrid, Mailgun, Resend ou outro?
- O professor/servidor permitira credenciais SMTP ou API?
- A verificacao de e-mail sera obrigatoria antes de usar o Chat IA?
- Usuarios nao verificados devem ser bloqueados ou apenas avisados?
- Qual sera a URL publica do app usada nos links de recuperacao e nos fluxos futuros por link?
- Quem gerencia os segredos no ambiente do servidor?
- Havera dominio proprio para melhorar reputacao de entrega?
- O projeto deve usar templates HTML ou mensagens simples em texto?
- Qual tempo de expiracao sera usado para codigos de cadastro e tokens de recuperacao?

## Criterios de Pronto para Implementacao Futura

Antes de implementar as fases 6 e 7, o projeto deve ter:

- Provedor escolhido ou modo fake/local explicitamente aceito.
- Variaveis de ambiente definidas em documentacao.
- `APP_PUBLIC_URL` definido para ambiente com envio real.
- Politica de logs seguros definida.
- Mensagens publicas neutras definidas.
- Decisao sobre bloquear ou apenas avisar usuarios com e-mail nao verificado.

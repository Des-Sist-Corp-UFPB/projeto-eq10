# Plano de Servico de E-mail - SIA/DATASUS

Atualizado em: 2026-06-21

Este documento planeja a estrategia de envio de e-mails para funcionalidades futuras de autenticacao. A fundacao interna de e-mail, a fundacao de verificacao de e-mail e a fundacao de recuperacao de senha ja existem em modo seguro/fake por padrao. Google login, historico de chat, health checks e envio real por SMTP/API continuam fora do escopo atual.

## Objetivo

O servico de e-mail devera apoiar, em fases futuras:

- Verificar que o usuario controla o e-mail cadastrado.
- Enviar links ou codigos de recuperacao de senha.
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
5. Suportar modo real depois, via SMTP ou provedor de API, usando variaveis de ambiente.
6. Nunca mostrar ao usuario que um e-mail real foi enviado quando o sistema estiver em modo fake/local.

Recomendacao pratica para a primeira implementacao futura:

- `EMAIL_ENABLED=false` por padrao.
- `EMAIL_PROVIDER=fake` em desenvolvimento/local.
- SMTP ou API provider apenas quando a equipe tiver credenciais e URL publica configuradas.
- Mensagens da interface devem diferenciar modo real e modo ainda nao configurado quando isso for necessario para evitar promessa falsa.

Implementacao inicial disponivel:

- Modulo: `src/auth/email_service.py`.
- Classe principal: `EmailService`.
- Resultado estruturado: `EmailSendResult`.
- Modo fake/local funcional por padrao.
- SMTP e provedores por API ficam preparados por configuracao, mas ainda nao enviam e-mail real.
- Fundacao de verificacao: `src/auth/email_verification_service.py`.
- Tabela de tokens: `email_verification_tokens`, armazenando somente `token_hash`.
- Campos de usuario: `email_verificado` e `email_verificado_em`.
- Controle de exigencia: `EMAIL_VERIFICATION_REQUIRED=false` por padrao, para nao bloquear login ou Chat IA enquanto o envio real nao estiver configurado.
- Se `EMAIL_VERIFICATION_REQUIRED=true`, o usuario ainda pode fazer login e acessar o perfil, mas o Chat IA fica bloqueado ate a verificacao do e-mail.
- Fundacao de recuperacao de senha: `src/auth/password_reset_service.py`.
- Tabela de tokens: `password_reset_tokens`, armazenando somente `token_hash`.
- Mensagem publica neutra: `Se houver uma conta com este e-mail, enviaremos instrucoes de recuperacao.`

Exemplo de comportamento seguro em modo fake/local:

- Verificacao de e-mail: informar que a verificacao por e-mail ainda nao esta ativa neste ambiente.
- Recuperacao de senha: usar mensagem neutra sem prometer envio real quando o ambiente estiver em modo fake/local.

## Variaveis de Ambiente Sugeridas

Configuracao comum:

```env
EMAIL_ENABLED=false
EMAIL_PROVIDER=fake
EMAIL_FROM=
APP_PUBLIC_URL=
```

Configuracao SMTP:

```env
EMAIL_PROVIDER=smtp
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
- `APP_PUBLIC_URL` sera necessario para montar links de verificacao e recuperacao.
- Em ambiente local sem URL publica, deve-se usar modo fake/local ou uma URL explicitamente configurada para teste.

## Seguranca

Regras obrigatorias para as fases futuras:

- Nunca registrar tokens de verificacao.
- Nunca registrar links completos de recuperacao ou verificacao.
- Nunca registrar credenciais SMTP.
- Nunca registrar API keys.
- Nunca registrar senhas ou hashes.
- Armazenar hash do token, nao o token bruto, sempre que possivel.
- Token deve expirar.
- Token deve ser de uso unico.
- Token usado deve ser marcado com `usado_em` ou equivalente.
- Mensagens publicas nao devem revelar se um e-mail existe no sistema.
- O fluxo de recuperacao deve usar mensagem neutra:

> Se houver uma conta com este e-mail, enviaremos instrucoes de recuperacao.

Tambem e recomendado:

- Mascarar e-mails em logs, por exemplo `a***@dominio.com`.
- Separar logs de auditoria de mensagens exibidas ao usuario.
- Garantir que erros de SMTP/API nao mostrem credenciais ou payloads sensiveis na interface.
- Usar tempo de expiracao curto para tokens de recuperacao.

## Integracao com Verificacao de E-mail

Fundacao implementada:

- Criacao de token seguro com `secrets.token_urlsafe`.
- Armazenamento apenas do hash SHA-256 do token.
- Expiracao do token.
- Marcacao de token usado com `usado_em`.
- Marcacao do usuario com `email_verificado = true` e `email_verificado_em` quando o token valido e confirmado.
- Reenvio pelo perfil usando o `EmailService`.
- Modo fake/local informa honestamente que o envio real depende de configuracao.

Fluxo completo planejado para ambiente com envio real:

1. Criar usuario com `email_verificado = false`.
2. Criar token de verificacao.
3. Armazenar apenas o hash do token.
4. Definir data de expiracao.
5. Enviar link ou codigo de verificacao por e-mail.
6. Usuario clica no link ou informa o codigo.
7. Sistema valida token, expiracao e uso unico.
8. Sistema define `email_verificado = true`.
9. Sistema preenche `email_verificado_em`.
10. Token e marcado como usado.

O envio real ainda depende de configuracao de provedor, `APP_PUBLIC_URL` e decisao da equipe sobre obrigatoriedade da verificacao.

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

## Notificacoes Futuras de Seguranca

Depois que o envio real estiver funcionando, o mesmo servico pode apoiar notificacoes como:

- Senha alterada.
- E-mail alterado ou solicitacao de alteracao de e-mail.
- Login suspeito, se houver criterio tecnico confiavel.
- Conta desativada.

Essas notificacoes devem ser simples, sem incluir tokens, senhas, hashes ou dados analiticos DATASUS.

## Decisoes Pendentes

- Qual provedor a equipe usara: SMTP, Gmail app password, SendGrid, Mailgun, Resend ou outro?
- O professor/servidor permitira credenciais SMTP ou API?
- A verificacao de e-mail sera obrigatoria antes de usar o Chat IA?
- Usuarios nao verificados devem ser bloqueados ou apenas avisados?
- Qual sera a URL publica do app usada nos links de verificacao e recuperacao?
- Quem gerencia os segredos no ambiente do servidor?
- Havera dominio proprio para melhorar reputacao de entrega?
- O projeto deve usar templates HTML ou mensagens simples em texto?
- Qual tempo de expiracao sera usado para tokens de verificacao e recuperacao?

## Criterios de Pronto para Implementacao Futura

Antes de implementar as fases 6 e 7, o projeto deve ter:

- Provedor escolhido ou modo fake/local explicitamente aceito.
- Variaveis de ambiente definidas em documentacao.
- `APP_PUBLIC_URL` definido para ambiente com envio real.
- Politica de logs seguros definida.
- Mensagens publicas neutras definidas.
- Decisao sobre bloquear ou apenas avisar usuarios com e-mail nao verificado.

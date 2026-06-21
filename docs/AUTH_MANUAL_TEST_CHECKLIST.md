# Checklist Manual de Autenticacao e E-mail

Atualizado em: 2026-06-21

Use este checklist antes de iniciar uma nova funcionalidade grande de roadmap.
Ele cobre apenas fluxos de autenticacao, e-mail fake/local, protecao do Chat IA
e seguranca de mensagens.

## Configuracao Base

- [ ] Rodar o app com `EMAIL_ENABLED=false`.
- [ ] Confirmar que `EMAIL_VERIFICATION_REQUIRED` esta ausente ou definido como `false`.
- [ ] Confirmar que a pagina inicial e `Estatisticas`.
- [ ] Confirmar que `Estatisticas` abre sem login.
- [ ] Confirmar que o link do painel de estatisticas continua funcionando.

## Cadastro, Login e Sessao

- [ ] Criar uma conta nova.
- [ ] Confirmar que a senha nao aparece na tela ou em logs.
- [ ] Confirmar que a mensagem de criacao nao promete envio real de e-mail em modo fake/local.
- [ ] Fazer login com a conta criada.
- [ ] Alternar entre `Estatisticas` e `Chat IA`.
- [ ] Confirmar que a sessao continua ativa.
- [ ] Fazer logout.
- [ ] Confirmar que `Chat IA` volta a exigir login.

## Perfil

- [ ] Abrir `Meu perfil`.
- [ ] Confirmar que nome e e-mail aparecem corretamente.
- [ ] Confirmar que o status do e-mail aparece como verificado ou nao verificado.
- [ ] Alterar nome e confirmar que atualiza na sessao.
- [ ] Alterar e-mail e confirmar que o status volta para nao verificado.
- [ ] Alterar senha com senha atual errada e confirmar erro amigavel.
- [ ] Alterar senha com senha atual correta e confirmar sucesso.
- [ ] Confirmar que erros antigos nao ficam presos ao trocar de formulario.

## Verificacao de E-mail

- [ ] Em modo fake/local, clicar em `Reenviar verificacao`.
- [ ] Confirmar que a UI nao promete envio real.
- [ ] Testar `?verify_email_token=token-invalido`.
- [ ] Confirmar mensagem amigavel de link invalido ou expirado.
- [ ] Confirmar que o token nao aparece na tela.
- [ ] Confirmar que o parametro e removido da URL quando possivel.
- [ ] Usar um token valido gerado em ambiente de teste.
- [ ] Confirmar mensagem de sucesso.
- [ ] Reutilizar o mesmo token.
- [ ] Confirmar mensagem amigavel de link ja utilizado.

## Recuperacao de Senha

- [ ] Clicar em `Esqueci minha senha`.
- [ ] Informar e-mail existente.
- [ ] Confirmar mensagem neutra:
  `Se houver uma conta com este e-mail, enviaremos instrucoes de recuperacao.`
- [ ] Informar e-mail inexistente.
- [ ] Confirmar exatamente a mesma mensagem neutra.
- [ ] Confirmar que nenhum token, hash ou link completo aparece na UI.
- [ ] Testar `?reset_password_token=token-invalido`.
- [ ] Confirmar mensagem amigavel de link invalido ou expirado.
- [ ] Usar token valido em ambiente de teste.
- [ ] Redefinir senha.
- [ ] Confirmar que a senha antiga nao funciona.
- [ ] Confirmar que a nova senha funciona.
- [ ] Reutilizar o mesmo token.
- [ ] Confirmar mensagem amigavel de link ja utilizado.

## EMAIL_VERIFICATION_REQUIRED

- [ ] Definir `EMAIL_VERIFICATION_REQUIRED=true` em ambiente de teste.
- [ ] Fazer login com usuario nao verificado.
- [ ] Confirmar que o login continua permitido.
- [ ] Confirmar que o Chat IA fica bloqueado.
- [ ] Confirmar que o usuario consegue abrir perfil e reenviar verificacao.
- [ ] Verificar o e-mail com token valido.
- [ ] Confirmar que o Chat IA passa a abrir normalmente.

## Desativacao de Conta

- [ ] Abrir `Meu perfil`.
- [ ] Clicar em `Desativar conta`.
- [ ] Cancelar/voltar uma vez e confirmar que a conta continua ativa.
- [ ] Repetir e confirmar digitando o e-mail.
- [ ] Confirmar que a sessao e encerrada.
- [ ] Confirmar que a conta nao consegue mais fazer login.
- [ ] Solicitar recuperacao de senha para a conta desativada.
- [ ] Confirmar mensagem neutra e que nenhum token utilizavel e enviado/criado.

## Chat IA

- [ ] Tentar acessar `Chat IA` sem login.
- [ ] Confirmar que o chat completo nao aparece.
- [ ] Fazer login.
- [ ] Confirmar que o input do Chat IA aparece.
- [ ] Clicar em uma pergunta sugerida.
- [ ] Confirmar que a pergunta aparece uma vez.
- [ ] Confirmar ordem: usuario, loading, resposta da assistente.
- [ ] Enviar pergunta fora do escopo.
- [ ] Confirmar mensagem amigavel, sem traceback.

## Seguranca Visual e Logs

- [ ] Confirmar que a UI nao mostra traceback Python.
- [ ] Confirmar que a UI nao mostra token cru.
- [ ] Confirmar que a UI nao mostra `token_hash`.
- [ ] Confirmar que a UI nao mostra URL completa com token.
- [ ] Confirmar que a UI nao mostra senha, hash de senha, API key, SMTP password ou string de conexao.
- [ ] Confirmar que logs tecnicos usam e-mail mascarado quando aplicavel.
- [ ] Confirmar que fluxos de auth/e-mail nao escrevem em `data_sus`, `dim_*` ou `vw_data_sus_ia`.

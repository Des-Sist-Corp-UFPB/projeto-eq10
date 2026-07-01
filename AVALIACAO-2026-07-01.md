# Avaliação — EQ10 (DSC)

**Data:** 2026-07-01  
**Avaliador:** Prof. Rodrigo  
**Método:** verificação automática cruzando o que o `README.md` declara com evidências no código-fonte (leitura de `origin/main`).

> Esta é uma avaliação automática preliminar. O que não estiver documentado no README e commitado no repositório é considerado não atendido.

---

## 1. Log de Auditoria

✅ **Atendido** — documentado no README e com 598 evidência(s) no código.

---

## 2. Integração com Serviço Externo

- ✅ **OpenAI** — declarado no README e comprovado no código (23 ocorrência(s)).
  - Evidência: `src/ai/pandasai_runner.py:14:DEFAULT_LLM_MODEL = "gpt-4.1-mini"`
- ✅ **MinIO** — declarado no README e comprovado no código (6 ocorrência(s)).
  - Evidência: `src/ui/styles.py:217:    """Return the configured public/signed logo URL without exposing MinIO credentials."""`
- ✅ **SMTP / e-mail** — declarado no README e comprovado no código (5 ocorrência(s)).
  - Evidência: `src/auth/email_service.py:138:    EMAIL_ENABLED=true e EMAIL_PROVIDER=smtp.`

_Detectado no código, mas **não documentado** no README (não pontua até ser descrito):_
- ℹ️ Resend
- ℹ️ SendGrid

---

## 3. Cobertura de Testes (≥ 85%)

⚠️ **Relatório incompleto** — há 2 arquivo(s) em `cobertura/`, mas o percentual total não pôde ser lido. Commite o relatório HTML completo.

> Observação: a cobertura é lida do relatório commitado pela equipe; não é recalculada nesta avaliação.

---

*Avaliação gerada automaticamente em 2026-07-01. Consulte `ORIENTACOES-AVALIACAO-2026-06-29.md` para os critérios.*
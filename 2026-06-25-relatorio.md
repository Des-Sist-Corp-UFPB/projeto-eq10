# Relatório de Avaliação — EQ10 (DSC)

| | |
|---|---|
| **Data** | 2026-06-25 |
| **Repositório** | https://github.com/des-sist-corp-ufpb/projeto-eq10 |
| **Aplicação** | https://eq10.dsc.rodrigor.com |
| **Período de atividade** | 2026-06-24 → 2026-06-24 |
| **Total de commits** (sem merges) | 1 |
| **Integrantes** | Gabriel Nunes Gomes (@Gabriel-Nunes-UFPB) |

---

## 1. Tecnologias

- Python
- SQLAlchemy

---

## 2. Análise Funcional

### Endpoints REST

Não detectados automaticamente.

---

## 3. Análise Arquitetural

| Aspecto | Status | Observação |
|---------|--------|-----------|
| Arquitetura em camadas | ❌ | controller=❌  service=✅  repository=❌ |
| Testes automatizados | ✅ | 32 arquivo(s) de teste |
| Migrations versionadas | ❌ | não encontradas |
| Logging | ✅ | @Slf4j / LoggerFactory / logging.getLogger detectado |
| Autenticação / Segurança | ✅ | Spring Security / JWT / decorator detectado |
| DTOs / Separação de dados | ❌ | não detectado |
| Tratamento global de exceções | ❌ | não detectado |
| Documentação de API (OpenAPI) | ❌ | não detectado |
| Variáveis de ambiente | ✅ | .env / @Value / os.environ detectado |
| Dockerfile / docker-compose | ✅ | presente |

---

## 4. Contribuição por Usuário

### Resumo

| Usuário | Commits | % commits | Linhas adicionadas | Linhas no código atual | % código atual |
|---------|---------|-----------|-------------------|----------------------|----------------|
| Gabriel Nunes Gomes (@Gabriel-Nunes-UFPB) | 1 | 100% | 55.015 | 19.586 | 100% |

### Contribuição por Camada

| Camada | Total linhas | Gabriel Nunes Gomes (@Gabriel-Nunes-UFPB) |
|--------|-------------|---------|
| Service | 7.853 | 100% |
| Test | 3.580 | 100% |

---

## 5. Contribuição por Funcionalidade

Baseado em `git blame` nos arquivos de controller e service.

| Arquivo | Total linhas | Gabriel Nunes Gomes (@Gabriel-Nunes-UFPB) |
|---------|-------------|---------|
| `user_service.py` | 910 | 100% |
| `email_change_service.py` | 657 | 100% |
| `chat_history_service.py` | 596 | 100% |
| `pending_registration_service.py` | 561 | 100% |
| `account_reactivation_service.py` | 523 | 100% |
| `email_verification_service.py` | 521 | 100% |
| `password_reset_service.py` | 467 | 100% |
| `email_service.py` | 450 | 100% |
| `test_auth_user_service.py` | 450 | 100% |
| `health_service.py` | 431 | 100% |
| `test_pending_registration_service.py` | 333 | 100% |
| `test_account_reactivation_service.py` | 286 | 100% |
| `test_email_change_service.py` | 285 | 100% |
| `test_email_service.py` | 281 | 100% |
| `test_password_reset_service.py` | 262 | 100% |
| `test_email_verification_service.py` | 244 | 100% |
| `test_health_service.py` | 222 | 100% |
| `audit_log_service.py` | 196 | 100% |
| `test_chat_history_service.py` | 178 | 100% |

---

*Relatório gerado automaticamente em 2026-06-25.*
*Os dados de contribuição são baseados em `git log --numstat` (linhas adicionadas) e `git blame` (linhas no código atual), excluindo commits de merge.*
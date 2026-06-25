# Relatório de Avaliação — EQ10 (DSC)

| | |
|---|---|
| **Data** | 2026-06-25 |
| **Repositório** | https://github.com/des-sist-corp-ufpb/projeto-eq10 |
| **Aplicação** | https://eq10.dsc.rodrigor.com |
| **Período de atividade** | 2026-06-24 → 2026-06-25 |
| **Total de commits** (sem merges, branch main) | 2 |
| **Integrantes** | Gabriel Nunes Gomes (@Gabriel-Nunes-UFPB), Heloisa Duarte De Andrade (@heloisaa27) |

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

| Usuário | Commits (main) | Commits (GitHub API) | Linhas adicionadas | Linhas no código atual | % código atual |
|---------|---------------|---------------------|-------------------|----------------------|----------------|
| Gabriel Nunes Gomes (@Gabriel-Nunes-UFPB) | 1 | **46** ⚠️ | 55.015 | 19.586 | 100% |
| Heloisa Duarte De Andrade (@heloisaa27) | 0 | **32** ⚠️ | 0 | 0 | 0% |
| *(sem login GitHub)* | 1 | 50% | — | — | — |

> **⚠️ Divergência entre commits locais e GitHub API:**
> - **@Gabriel-Nunes-UFPB**: 1 commit(s) na branch `main` vs **46** registrados na API GitHub (commits em branches não mergeadas ou absorvidos via squash-merge sem preservação de autoria).
> - **@heloisaa27**: 0 commit(s) na branch `main` vs **32** registrados na API GitHub (commits em branches não mergeadas ou absorvidos via squash-merge sem preservação de autoria).
>

### Contribuição por Camada

| Camada | Total linhas | Gabriel Nunes Gomes (@Gabriel-Nunes-UFPB) | Heloisa Duarte De Andrade (@heloisaa27) |
|--------|-------------|---------|---------|
| Service | 7.853 | 100% | 0% |
| Test | 3.580 | 100% | 0% |

---

## 5. Contribuição por Funcionalidade

Baseado em `git blame` nos arquivos de controller e service.

| Arquivo | Total linhas | Gabriel Nunes Gomes (@Gabriel-Nunes-UFPB) | Heloisa Duarte De Andrade (@heloisaa27) |
|---------|-------------|---------|---------|
| `user_service.py` | 910 | 100% | 0% |
| `email_change_service.py` | 657 | 100% | 0% |
| `chat_history_service.py` | 596 | 100% | 0% |
| `pending_registration_service.py` | 561 | 100% | 0% |
| `account_reactivation_service.py` | 523 | 100% | 0% |
| `email_verification_service.py` | 521 | 100% | 0% |
| `password_reset_service.py` | 467 | 100% | 0% |
| `email_service.py` | 450 | 100% | 0% |
| `test_auth_user_service.py` | 450 | 100% | 0% |
| `health_service.py` | 431 | 100% | 0% |
| `test_pending_registration_service.py` | 333 | 100% | 0% |
| `test_account_reactivation_service.py` | 286 | 100% | 0% |
| `test_email_change_service.py` | 285 | 100% | 0% |
| `test_email_service.py` | 281 | 100% | 0% |
| `test_password_reset_service.py` | 262 | 100% | 0% |
| `test_email_verification_service.py` | 244 | 100% | 0% |
| `test_health_service.py` | 222 | 100% | 0% |
| `audit_log_service.py` | 196 | 100% | 0% |
| `test_chat_history_service.py` | 178 | 100% | 0% |

---

*Relatório gerado automaticamente em 2026-06-25.*
*Os dados de contribuição são baseados em `git log --numstat` (linhas adicionadas) e `git blame` (linhas no código atual), excluindo commits de merge.*
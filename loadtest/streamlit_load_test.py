"""Standard-library load tests for Streamlit UI and internal services.

This script does not install or require Playwright/Selenium. HTTP scenarios
measure concurrent access to the Streamlit interface. Internal scenarios call
project services directly to exercise application logic and database paths.

Usage:
    python loadtest/streamlit_load_test.py --url http://localhost:8080
    python loadtest/streamlit_load_test.py --scenario http
    python loadtest/streamlit_load_test.py --scenario internal --allow-internal-writes
"""

from __future__ import annotations

import argparse
import concurrent.futures
import datetime as dt
import os
import statistics
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable


DEFAULT_USERS = [50, 100, 200, 300, 500, 750, 1000]
DEFAULT_INTERNAL_USERS = [1, 2, 5, 10, 20, 30, 50]
DEFAULT_URL = "http://localhost:8080"
DEFAULT_REQUESTS_PER_USER = 3
DEFAULT_TIMEOUT_SECONDS = 3
DEFAULT_OUTPUT = "relatorio_carga.txt"
P95_LIMIT_SECONDS = 1.0
HIGH_ERROR_RATE = 0.20
HARD_MAX_USERS = 1500
PRODUCTION_ENV_VALUES = {"prod", "production", "staging", "homolog", "homologacao"}
LOCAL_DB_HOSTS = {"", "localhost", "127.0.0.1", "::1", "db", "postgres", "postgresql", "database"}


@dataclass(frozen=True)
class Scenario:
    key: str
    title: str
    group: str
    objective: str
    operation_kind: str
    writes_database: bool
    executable: bool = True
    method: str | None = None
    url_factory: Callable[[str], str] | None = None
    limitation: str | None = None
    requires_write_permission: bool = False


@dataclass(frozen=True)
class OperationResult:
    elapsed_seconds: float
    ok: bool
    status: str
    error: str | None = None


@dataclass(frozen=True)
class LoadResult:
    scenario_key: str
    users: int
    total_operations: int
    errors: int
    error_rate: float
    status_counts: dict[str, int]
    average_seconds: float
    p95_seconds: float
    p99_seconds: float
    max_seconds: float
    target: str


@dataclass(frozen=True)
class ScenarioReport:
    scenario: Scenario
    results: list[LoadResult]
    notes: list[str]


def configure_project_imports() -> None:
    project_root = Path(__file__).resolve().parents[1]
    src_dir = project_root / "src"
    for path in (project_root, src_dir):
        text_path = str(path)
        if text_path not in sys.path:
            sys.path.insert(0, text_path)


def database_host_from_url(raw_url: str) -> str:
    if not raw_url:
        return ""
    parsed = urllib.parse.urlparse(raw_url)
    if parsed.scheme.startswith("sqlite"):
        return ""
    return (parsed.hostname or "").strip().lower()


def configured_database_hosts() -> list[str]:
    hosts: list[str] = []
    for env_name in ("AUTH_DATABASE_URL", "DATABASE_URL"):
        host = database_host_from_url(os.getenv(env_name, ""))
        if host:
            hosts.append(host)
    for env_name in ("AUTH_DB_HOST", "DB_HOST", "host"):
        host = os.getenv(env_name, "").strip().lower()
        if host:
            hosts.append(host)
    return hosts


def internal_write_block_reason() -> str | None:
    for env_name in ("ENVIRONMENT", "APP_ENV", "PYTHON_ENV", "STREAMLIT_ENV"):
        value = os.getenv(env_name, "").strip().lower()
        if value in PRODUCTION_ENV_VALUES:
            return f"{env_name}={value}"

    remote_hosts = [host for host in configured_database_hosts() if host not in LOCAL_DB_HOSTS]
    if remote_hosts:
        return "database host nao local configurado"

    return None


def with_query(base_url: str, **params: str) -> str:
    parsed = urllib.parse.urlparse(base_url)
    current_params = dict(urllib.parse.parse_qsl(parsed.query, keep_blank_values=True))
    current_params.update(params)
    query = urllib.parse.urlencode(current_params)
    return urllib.parse.urlunparse(parsed._replace(query=query))


def build_scenarios() -> dict[str, Scenario]:
    return {
        "home": Scenario(
            key="home",
            title="HTTP GET da pagina inicial",
            group="http",
            objective="Medir acesso concorrente ao carregamento basico da interface.",
            operation_kind="HTTP/interface",
            writes_database=False,
            method="GET",
            url_factory=lambda base_url: base_url,
        ),
        "chat_page": Scenario(
            key="chat_page",
            title="HTTP GET da pagina Chat IA",
            group="http",
            objective="Medir acesso concorrente a rota de interface do Chat IA.",
            operation_kind="HTTP/interface",
            writes_database=False,
            method="GET",
            url_factory=lambda base_url: with_query(base_url, page="chat-ia"),
            limitation=(
                "Este cenario mede a pagina/gate do Chat IA. Envio de mensagem em Streamlit usa "
                "session_state/WebSocket e nao e submetido por HTTP REST direto."
            ),
        ),
        "user_create": Scenario(
            key="user_create",
            title="Servico interno: criacao de usuario",
            group="internal",
            objective="Chamar UserService.create_user com e-mails ficticios unicos.",
            operation_kind="servico interno/logica+banco",
            writes_database=True,
            requires_write_permission=True,
        ),
        "auth_login": Scenario(
            key="auth_login",
            title="Servico interno: login/autenticacao",
            group="internal",
            objective="Chamar UserService.authenticate com usuario de teste criado pelo script.",
            operation_kind="servico interno/logica+banco",
            writes_database=True,
            requires_write_permission=True,
            limitation="A senha de teste e gerada em memoria por execucao e nunca e gravada no relatorio.",
        ),
        "audit_read": Scenario(
            key="audit_read",
            title="Servico interno: leitura de auditoria",
            group="internal",
            objective="Chamar AuditLogService.get_recent_logs para medir leitura de auditoria.",
            operation_kind="servico interno/leitura banco",
            writes_database=False,
        ),
        "chat_mock": Scenario(
            key="chat_mock",
            title="Servico interno: chat com provider mockado",
            group="internal",
            objective="Criar sessao e mensagens de chat com resposta mockada, sem chamar IA externa.",
            operation_kind="servico interno/logica+banco",
            writes_database=True,
            requires_write_permission=True,
            limitation=(
                "Nao chama LLM nem provider externo. O teste exercita persistencia de historico "
                "com uma resposta local fixa."
            ),
        ),
    }


def timed_operation(operation: Callable[[], str]) -> OperationResult:
    started = time.perf_counter()
    try:
        status = operation()
        return OperationResult(time.perf_counter() - started, True, status)
    except Exception as exc:
        return OperationResult(time.perf_counter() - started, False, "ERROR", type(exc).__name__)


def fetch_http(method: str, url: str, timeout_seconds: int) -> OperationResult:
    started = time.perf_counter()
    request = urllib.request.Request(url, headers={"User-Agent": "stdlib-load-test/1.0"}, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            response.read()
            status = response.getcode()
            return OperationResult(time.perf_counter() - started, 200 <= status < 400, str(status))
    except urllib.error.HTTPError as exc:
        return OperationResult(time.perf_counter() - started, False, str(exc.code), str(exc))
    except Exception as exc:
        return OperationResult(time.perf_counter() - started, False, "SEM_RESPOSTA", type(exc).__name__)


def percentile(values: list[float], percent: float) -> float:
    if not values:
        return 0.0
    sorted_values = sorted(values)
    index = int((percent / 100) * (len(sorted_values) - 1))
    return sorted_values[index]


def load_project_services() -> tuple[Any, Any, Any]:
    configure_project_imports()

    from src.audit.audit_log_service import AuditLogService
    from src.auth.user_service import UserService
    from src.chat.chat_history_service import ChatHistoryService

    user_service = UserService.from_environment()
    audit_service = AuditLogService(user_service.engine)
    chat_service = ChatHistoryService(user_service.engine)
    return user_service, audit_service, chat_service


def unique_email(prefix: str, run_id: str, users: int, sequence: int) -> str:
    return f"loadtest+{prefix}-{run_id}-{users}-{sequence}@example.invalid"


def build_test_password(run_id: str) -> str:
    return f"LoadTest-{run_id}-local-only!"


def prepare_login_user(user_service: Any, run_id: str) -> tuple[str, str]:
    email = unique_email("login", run_id, 0, 0)
    test_password = build_test_password(run_id)
    try:
        user = user_service.create_user("Load Test Login", email, test_password, test_password)
    except Exception:
        pass
    else:
        track_created_user(user_service, int(user.id))
    return email, test_password


def prepare_chat_user(user_service: Any, run_id: str) -> int:
    email = unique_email("chat", run_id, 0, 0)
    test_password = build_test_password(run_id)
    try:
        user = user_service.create_user("Load Test Chat", email, test_password, test_password)
    except Exception:
        user = user_service.authenticate(email, test_password)
    else:
        track_created_user(user_service, int(user.id))
    return int(user.id)


def cleanup_state() -> dict[str, Any]:
    return {
        "created_user_ids": [],
        "created_chat_sessions": [],
        "lock": threading.Lock(),
    }


def track_created_user(user_service: Any, user_id: int) -> None:
    state = getattr(user_service, "_loadtest_cleanup", None)
    if not state:
        return
    with state["lock"]:
        state["created_user_ids"].append(user_id)


def track_created_chat_session(chat_service: Any, session_id: int, user_id: int) -> None:
    state = getattr(chat_service, "_loadtest_cleanup", None)
    if not state:
        return
    with state["lock"]:
        state["created_chat_sessions"].append((session_id, user_id))


def cleanup_created_data(services: tuple[Any, Any, Any] | None) -> list[str]:
    if services is None:
        return []

    user_service, _audit_service, chat_service = services
    state = getattr(user_service, "_loadtest_cleanup", None)
    if not state:
        return []

    notes: list[str] = []
    with state["lock"]:
        chat_sessions = list(state["created_chat_sessions"])
        user_ids = list(dict.fromkeys(state["created_user_ids"]))

    deleted_sessions = 0
    for session_id, user_id in chat_sessions:
        try:
            chat_service.soft_delete_chat_session(session_id, user_id)
            deleted_sessions += 1
        except Exception:
            pass
    if chat_sessions:
        notes.append(f"Limpeza: {deleted_sessions}/{len(chat_sessions)} sessoes de chat marcadas como deletadas.")

    deleted_users = 0
    for user_id in user_ids:
        try:
            user_service.soft_delete_user(user_id)
            deleted_users += 1
        except Exception:
            pass
    if user_ids:
        notes.append(f"Limpeza: {deleted_users}/{len(user_ids)} usuarios de teste marcados como deletados.")

    return notes


def internal_operation_factory(
    scenario: Scenario,
    services: tuple[Any, Any, Any],
    run_id: str,
    seed_data: dict[str, Any],
) -> Callable[[int, int], OperationResult]:
    user_service, audit_service, chat_service = services

    if scenario.key == "user_create":
        def create_user(users: int, sequence: int) -> OperationResult:
            def operation() -> str:
                email = unique_email("user", run_id, users, sequence)
                test_password = build_test_password(run_id)
                user = user_service.create_user("Load Test User", email, test_password, test_password)
                track_created_user(user_service, int(user.id))
                return "CREATED"

            return timed_operation(operation)

        return create_user

    if scenario.key == "auth_login":
        login_email, login_password = seed_data["login_credentials"]

        def login(_users: int, _sequence: int) -> OperationResult:
            return timed_operation(lambda: "AUTH_OK" if user_service.authenticate(login_email, login_password) else "ERROR")

        return login

    if scenario.key == "audit_read":
        def read_audit(_users: int, _sequence: int) -> OperationResult:
            def operation() -> str:
                audit_service.get_recent_logs(limit=50)
                return "READ_OK"

            return timed_operation(operation)

        return read_audit

    if scenario.key == "chat_mock":
        user_id = seed_data["chat_user_id"]

        def chat_mock(_users: int, sequence: int) -> OperationResult:
            def operation() -> str:
                session = chat_service.create_chat_session(user_id, title=f"Load test {run_id}-{sequence}")
                track_created_chat_session(chat_service, int(session.id), user_id)
                chat_service.add_chat_message(session.id, user_id, "user", "Qual o total de procedimentos?")
                chat_service.add_chat_message(session.id, user_id, "assistant", "Resposta mockada para teste de carga.")
                return "CHAT_MOCK_OK"

            return timed_operation(operation)

        return chat_mock

    raise ValueError(f"cenario interno desconhecido: {scenario.key}")


def run_concurrent_operations(
    scenario: Scenario,
    users: int,
    requests_per_user: int,
    target: str,
    operation: Callable[[int, int], OperationResult],
) -> LoadResult:
    total_operations = users * requests_per_user
    with concurrent.futures.ThreadPoolExecutor(max_workers=users) as executor:
        futures = [
            executor.submit(operation, users, sequence)
            for sequence in range(total_operations)
        ]
        results = [future.result() for future in concurrent.futures.as_completed(futures)]

    elapsed_times = [result.elapsed_seconds for result in results]
    errors = sum(1 for result in results if not result.ok)
    status_counts = Counter(result.status for result in results)

    return LoadResult(
        scenario_key=scenario.key,
        users=users,
        total_operations=total_operations,
        errors=errors,
        error_rate=errors / total_operations if total_operations else 0.0,
        status_counts=dict(sorted(status_counts.items())),
        average_seconds=statistics.fmean(elapsed_times) if elapsed_times else 0.0,
        p95_seconds=percentile(elapsed_times, 95),
        p99_seconds=percentile(elapsed_times, 99),
        max_seconds=max(elapsed_times, default=0.0),
        target=target,
    )


def first_p95_over_limit(results: list[LoadResult]) -> LoadResult | None:
    return next((result for result in results if result.p95_seconds >= P95_LIMIT_SECONDS), None)


def highest_stable_load(results: list[LoadResult]) -> LoadResult | None:
    stable = [
        result
        for result in results
        if result.total_operations > 0
        and result.p95_seconds < P95_LIMIT_SECONDS
        and result.error_rate < HIGH_ERROR_RATE
    ]
    return stable[-1] if stable else None


def format_counts(status_counts: dict[str, int]) -> str:
    if not status_counts:
        return "-"
    return ", ".join(f"{status}={count}" for status, count in status_counts.items())


def format_scenario_report(report: ScenarioReport) -> list[str]:
    scenario = report.scenario
    lines = [
        "",
        f"## Cenario: {scenario.title} ({scenario.key})",
        f"Grupo: {scenario.group}",
        f"Objetivo: {scenario.objective}",
        f"Tipo: {scenario.operation_kind}",
        f"Escrita no banco: {'sim' if scenario.writes_database else 'nao'}",
    ]
    if scenario.method:
        lines.append(f"Metodo HTTP: {scenario.method}")
    if scenario.limitation:
        lines.append(f"Observacao: {scenario.limitation}")
    for note in report.notes:
        lines.append(f"Nota: {note}")

    if not report.results:
        lines.append("Status: nao executado nesta rodada.")
        return lines

    lines.extend(
        [
            "",
            "usuarios | operacoes | erros | erro_% | status | media_s | p95_s | p99_s | max_s | observacao",
            "---------|-----------|-------|--------|--------|---------|-------|-------|-------|-----------",
        ]
    )

    for result in report.results:
        observations = []
        if result.p95_seconds >= P95_LIMIT_SECONDS:
            observations.append("p95 >= 1s")
        if result.error_rate >= HIGH_ERROR_RATE:
            observations.append("taxa de erro alta")
        lines.append(
            f"{result.users:8d} | "
            f"{result.total_operations:9d} | "
            f"{result.errors:5d} | "
            f"{result.error_rate:6.1%} | "
            f"{format_counts(result.status_counts):6s} | "
            f"{result.average_seconds:7.3f} | "
            f"{result.p95_seconds:5.3f} | "
            f"{result.p99_seconds:5.3f} | "
            f"{result.max_seconds:5.3f} | "
            f"{', '.join(observations)}"
        )

    first_over_limit = first_p95_over_limit(report.results)
    stable_load = highest_stable_load(report.results)
    lines.append("")
    if first_over_limit:
        lines.append(
            "Primeira carga em que p95 >= 1s: "
            f"{first_over_limit.users} usuarios simultaneos "
            f"(p95={first_over_limit.p95_seconds:.3f}s)."
        )
    else:
        lines.append("O p95 nao passou de 1s nas cargas testadas.")

    if stable_load:
        lines.append(
            "Maior carga estavel abaixo de 1s: "
            f"{stable_load.users} usuarios simultaneos "
            f"(p95={stable_load.p95_seconds:.3f}s, erros={stable_load.error_rate:.1%})."
        )
    else:
        lines.append("Nao houve carga estavel abaixo de 1s nos criterios do teste.")

    lines.append("")
    lines.append("Alvos/operações realizadas:")
    for result in report.results:
        lines.append(f"- {result.users} usuarios: {result.target} -> {format_counts(result.status_counts)}")
    return lines


def format_report(
    base_url: str,
    scenario_reports: list[ScenarioReport],
    requests_per_user: int,
    timeout: int,
    allow_internal_writes: bool,
) -> str:
    generated_at = dt.datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %z")
    lines = [
        "Relatorio de teste de carga Streamlit",
        f"Gerado em: {generated_at}",
        f"URL base testada: {base_url}",
        f"Operacoes por usuario simultaneo: {requests_per_user}",
        f"Timeout HTTP por operacao: {timeout}s",
        f"Parada por p95: >= {P95_LIMIT_SECONDS:.1f}s",
        f"Parada por taxa de erro alta: >= {HIGH_ERROR_RATE:.0%}",
        f"Escritas internas habilitadas: {'sim' if allow_internal_writes else 'nao'}",
        "",
        "Interpretacao:",
        "- Testes HTTP medem acesso concorrente a interface Streamlit por GET.",
        "- Testes internos chamam servicos Python do projeto e medem logica/banco, nao renderizacao do navegador.",
        "- Streamlit nao expoe endpoints REST diretos para formularios; por isso cadastro/login/chat real nao sao testados via POST HTTP.",
        "- O chat interno usa resposta mockada local e nao chama IA externa real.",
        "- O script nao registra senhas, tokens ou segredos no relatorio.",
        "- Rode preferencialmente contra ambiente local, nunca contra producao compartilhada.",
    ]

    for scenario_report in scenario_reports:
        lines.extend(format_scenario_report(scenario_report))

    lines.extend(
        [
            "",
            "Como rodar:",
            "python loadtest/streamlit_load_test.py --url http://localhost:8080 --scenario http",
            "python loadtest/streamlit_load_test.py --scenario internal --allow-internal-writes",
            "python loadtest/streamlit_load_test.py --scenario audit_read",
            "python loadtest/streamlit_load_test.py --scenario all --users 1,2,5 --allow-internal-writes",
            "python loadtest/streamlit_load_test.py --scenario http --max-users 1000 --step 100",
        ]
    )
    return "\n".join(lines) + "\n"


def parse_users(value: str) -> list[int]:
    users = [int(item.strip()) for item in value.split(",") if item.strip()]
    if not users or any(user < 1 for user in users):
        raise argparse.ArgumentTypeError("use uma lista de inteiros positivos, exemplo: 50,100,200")
    return users


def build_user_loads(
    explicit_users: list[int] | None,
    max_users: int | None,
    step: int | None,
    default_users: list[int],
) -> list[int]:
    if explicit_users is not None:
        users = explicit_users
    elif max_users is not None or step is not None:
        final_max = max_users or max(default_users)
        final_step = step or default_users[0]
        if final_max < 1 or final_step < 1:
            raise argparse.ArgumentTypeError("--max-users e --step devem ser positivos")
        users = list(range(final_step, final_max + 1, final_step))
        if not users or users[-1] != final_max:
            users.append(final_max)
    else:
        users = default_users

    if max(users) > HARD_MAX_USERS:
        raise argparse.ArgumentTypeError(f"limite defensivo: no maximo {HARD_MAX_USERS} usuarios")
    return sorted(dict.fromkeys(users))


def select_scenarios(selected: str, scenarios: dict[str, Scenario]) -> list[Scenario]:
    if selected == "all":
        return [scenarios[key] for key in ("home", "chat_page", "user_create", "auth_login", "audit_read", "chat_mock")]
    if selected == "http":
        return [scenario for scenario in scenarios.values() if scenario.group == "http"]
    if selected == "internal":
        return [scenario for scenario in scenarios.values() if scenario.group == "internal"]
    return [scenarios[selected]]


def run_http_scenario(
    scenario: Scenario,
    base_url: str,
    user_loads: list[int],
    requests_per_user: int,
    timeout: int,
    continue_after_limit: bool,
) -> ScenarioReport:
    assert scenario.method and scenario.url_factory
    url = scenario.url_factory(base_url)
    operation = lambda _users, _sequence: fetch_http(scenario.method or "GET", url, timeout)
    return run_scenario_loads(
        scenario,
        user_loads,
        requests_per_user,
        target=f"{scenario.method} {url}",
        operation=operation,
        continue_after_limit=continue_after_limit,
        notes=[],
    )


def run_internal_scenario(
    scenario: Scenario,
    user_loads: list[int],
    requests_per_user: int,
    continue_after_limit: bool,
    allow_internal_writes: bool,
    write_block_reason: str | None,
    services: tuple[Any, Any, Any] | None,
    run_id: str,
    seed_data: dict[str, Any],
) -> ScenarioReport:
    notes: list[str] = []
    if scenario.requires_write_permission and not allow_internal_writes:
        notes.append("Nao executado: requer --allow-internal-writes para evitar escrita acidental em banco.")
        return ScenarioReport(scenario, [], notes)

    if scenario.requires_write_permission and write_block_reason:
        notes.append(f"Nao executado: escrita bloqueada por ambiente/banco possivelmente nao local ({write_block_reason}).")
        return ScenarioReport(scenario, [], notes)

    if services is None:
        notes.append("Nao executado: nao foi possivel carregar servicos internos/dependencias do projeto.")
        return ScenarioReport(scenario, [], notes)

    try:
        if scenario.key == "auth_login" and "login_credentials" not in seed_data:
            seed_data["login_credentials"] = prepare_login_user(services[0], run_id)
        if scenario.key == "chat_mock" and "chat_user_id" not in seed_data:
            seed_data["chat_user_id"] = prepare_chat_user(services[0], run_id)
        operation = internal_operation_factory(scenario, services, run_id, seed_data)
    except Exception as exc:
        notes.append(f"Nao executado: falha ao preparar cenario interno ({type(exc).__name__}).")
        return ScenarioReport(scenario, [], notes)

    return run_scenario_loads(
        scenario,
        user_loads,
        requests_per_user,
        target=scenario.operation_kind,
        operation=operation,
        continue_after_limit=continue_after_limit,
        notes=notes,
    )


def run_scenario_loads(
    scenario: Scenario,
    user_loads: list[int],
    requests_per_user: int,
    target: str,
    operation: Callable[[int, int], OperationResult],
    continue_after_limit: bool,
    notes: list[str],
) -> ScenarioReport:
    results: list[LoadResult] = []
    for users in user_loads:
        result = run_concurrent_operations(scenario, users, requests_per_user, target, operation)
        results.append(result)
        print(
            f"{scenario.key} | {users} usuarios: {result.total_operations} ops, "
            f"{result.errors} erros ({result.error_rate:.1%}), "
            f"status {result.status_counts}, "
            f"media {result.average_seconds:.3f}s, "
            f"p95 {result.p95_seconds:.3f}s, "
            f"p99 {result.p99_seconds:.3f}s, "
            f"max {result.max_seconds:.3f}s"
        )
        over_latency = result.p95_seconds >= P95_LIMIT_SECONDS
        high_errors = result.error_rate >= HIGH_ERROR_RATE
        if (over_latency or high_errors) and not continue_after_limit:
            reasons = []
            if over_latency:
                reasons.append("p95 >= 1s")
            if high_errors:
                reasons.append(f"taxa de erro >= {HIGH_ERROR_RATE:.0%}")
            print(f"{scenario.key}: parando em {users} usuarios: {', '.join(reasons)}.")
            break

    return ScenarioReport(scenario, results, notes)


def main() -> int:
    scenarios = build_scenarios()
    choices = ["all", "http", "internal", *scenarios.keys()]
    parser = argparse.ArgumentParser(description="Teste de carga Streamlit usando apenas biblioteca padrao.")
    parser.add_argument("--url", default=DEFAULT_URL, help=f"URL base. Padrao: {DEFAULT_URL}")
    parser.add_argument("--scenario", choices=choices, default="all", help="Cenario/grupo a executar. Padrao: all.")
    parser.add_argument("--users", type=parse_users, default=None, help="Cargas separadas por virgula.")
    parser.add_argument("--max-users", type=int, default=None, help="Maior carga a testar ao gerar por intervalo.")
    parser.add_argument("--step", type=int, default=None, help="Incremento de usuarios ao gerar por intervalo.")
    parser.add_argument(
        "--requests-per-user",
        type=int,
        default=DEFAULT_REQUESTS_PER_USER,
        help=f"Operacoes por usuario simultaneo. Padrao: {DEFAULT_REQUESTS_PER_USER}",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=DEFAULT_TIMEOUT_SECONDS,
        help=f"Timeout HTTP por operacao em segundos. Padrao: {DEFAULT_TIMEOUT_SECONDS}",
    )
    parser.add_argument("--output", default=DEFAULT_OUTPUT, help=f"Arquivo de saida. Padrao: {DEFAULT_OUTPUT}")
    parser.add_argument(
        "--allow-internal-writes",
        action="store_true",
        help="Permite cenarios internos que criam usuarios, logins/auditoria ou historico de chat.",
    )
    parser.add_argument(
        "--continue-after-limit",
        action="store_true",
        help="Continua testando mesmo se o p95 passar de 1s ou a taxa de erro ficar alta.",
    )
    args = parser.parse_args()

    if args.requests_per_user < 1 or args.timeout < 1:
        parser.error("--requests-per-user e --timeout devem ser positivos")

    selected_scenarios = select_scenarios(args.scenario, scenarios)
    default_users = DEFAULT_INTERNAL_USERS if all(s.group == "internal" for s in selected_scenarios) else DEFAULT_USERS
    try:
        user_loads = build_user_loads(args.users, args.max_users, args.step, default_users)
    except argparse.ArgumentTypeError as exc:
        parser.error(str(exc))

    services: tuple[Any, Any, Any] | None = None
    write_block_reason = internal_write_block_reason()
    if any(s.group == "internal" for s in selected_scenarios):
        os.environ.setdefault("ENVIRONMENT", "loadtest")
        try:
            services = load_project_services()
            state = cleanup_state()
            setattr(services[0], "_loadtest_cleanup", state)
            setattr(services[2], "_loadtest_cleanup", state)
        except Exception as exc:
            print(f"internal: servicos nao carregados ({type(exc).__name__}); cenarios internos serao documentados.")

    run_id = dt.datetime.now().strftime("%Y%m%d%H%M%S")
    seed_data: dict[str, Any] = {}
    scenario_reports: list[ScenarioReport] = []
    for scenario in selected_scenarios:
        if scenario.group == "http":
            scenario_reports.append(
                run_http_scenario(
                    scenario,
                    args.url,
                    user_loads,
                    args.requests_per_user,
                    args.timeout,
                    args.continue_after_limit,
                )
            )
        else:
            scenario_reports.append(
                run_internal_scenario(
                    scenario,
                    user_loads,
                    args.requests_per_user,
                    args.continue_after_limit,
                    args.allow_internal_writes,
                    write_block_reason,
                    services,
                    run_id,
                    seed_data,
                )
            )

    cleanup_notes = cleanup_created_data(services)
    if cleanup_notes:
        for report in reversed(scenario_reports):
            if report.scenario.group == "internal":
                report.notes.extend(cleanup_notes)
                break

    report = format_report(args.url, scenario_reports, args.requests_per_user, args.timeout, args.allow_internal_writes)
    Path(args.output).write_text(report, encoding="utf-8")
    print(f"Relatorio salvo em {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

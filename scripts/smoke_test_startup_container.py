"""Smoke test Linux/Docker do stack FastAPI (uvicorn) + Nginx.

Rewritten for the app/ FastAPI container (Dockerfile.fastapi / start_fastapi.sh).
The previous version of this script tested the Streamlit container's 3-process
supervisor (readiness_server + streamlit + nginx, /ping + /health with exact JSON
bodies, ports 8501/8502, PID files under /tmp/eq10-{readiness,streamlit,nginx}.pid).
None of that exists in the FastAPI image: it's a 2-process supervisor (uvicorn +
nginx), the only HTTP endpoint is /healthcheck (always HTTP 200, status "ok" or
"error" in the JSON body — see app/routes/healthcheck.py), and PID files are
/tmp/eq10-{uvicorn,nginx}.pid (see start_fastapi.sh). Same test *shape* as before —
verify the container starts, verify the supervisor brings the whole container down
when its core process dies — just re-pointed at the real process model.

Deliberately does NOT require a reachable Postgres: AUTH_DB_HOST is set to a
hostname that can't resolve, so get_auth_connection() fails fast. This is fine by
design — app/database/schema_check.py's startup check tolerates that (logs a
warning, doesn't crash), and GET /healthcheck always returns HTTP 200 with
status: "error" in that case, which is exactly what this test asserts.
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
import urllib.error
import urllib.request

CONTAINER_NAME = "eq10-startup-smoke"
HOST_PORT = 18080
PID_FILES = {
    "uvicorn": "/tmp/eq10-uvicorn.pid",
    "nginx": "/tmp/eq10-nginx.pid",
}
EXPECTED_COMMAND_ARGUMENTS = {
    "uvicorn": "uvicorn",
    "nginx": "nginx",
}


def _run(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(args),
        check=check,
        capture_output=True,
        text=True,
        timeout=120,
    )


def _request(path: str) -> tuple[int, bytes]:
    try:
        with urllib.request.urlopen(
            f"http://127.0.0.1:{HOST_PORT}{path}",
            timeout=5,
        ) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


def _wait_for(path: str, expected_status: int, timeout: float = 60) -> bytes:
    deadline = time.monotonic() + timeout
    last_status = 0
    while time.monotonic() < deadline:
        try:
            last_status, body = _request(path)
            if last_status == expected_status:
                return body
        except OSError:
            pass
        time.sleep(1)
    raise RuntimeError(f"safe_http_wait_failed:{path}:{last_status}")


def _process_signal_script(component: str) -> str:
    if component not in PID_FILES:
        raise ValueError("unknown_component")
    pid_file = PID_FILES[component]
    expected_argument = EXPECTED_COMMAND_ARGUMENTS[component]
    return (
        "import os,signal;"
        f"component={component!r};"
        f"pid_file={pid_file!r};"
        f"expected={expected_argument!r}.encode();"
        "\ntry:\n"
        " raw=open(pid_file,'rb').read().strip()\n"
        "except OSError:\n"
        " print(f'PROCESS_LOOKUP | component={component} | status=not_found');"
        " raise SystemExit(3)\n"
        "if not raw.isdigit() or int(raw)<=1:\n"
        " print(f'PROCESS_LOOKUP | component={component} | status=invalid');"
        " raise SystemExit(3)\n"
        "pid=int(raw)\n"
        "if pid==os.getpid() or not os.path.isdir(f'/proc/{pid}'):\n"
        " print(f'PROCESS_LOOKUP | component={component} | status=stale');"
        " raise SystemExit(3)\n"
        "try:\n"
        " args=open(f'/proc/{pid}/cmdline','rb').read().split(b'\\0')\n"
        "except OSError:\n"
        " print(f'PROCESS_LOOKUP | component={component} | status=stale');"
        " raise SystemExit(3)\n"
        "if expected not in args:\n"
        " print(f'PROCESS_LOOKUP | component={component} | status=wrong_component');"
        " raise SystemExit(3)\n"
        "print(f'PROCESS_LOOKUP | component={component} | status=verified | pid={pid}')\n"
        "os.kill(pid,signal.SIGTERM)"
    )


def _signal_process(component: str) -> None:
    code = _process_signal_script(component)
    result = _run(
        "docker",
        "exec",
        CONTAINER_NAME,
        "/app/.venv/bin/python",
        "-c",
        code,
        check=False,
    )
    if result.stdout:
        print(result.stdout.strip())
    if result.returncode != 0:
        raise RuntimeError(f"process_lookup_failed:{component}")


def _container_running() -> bool:
    result = _run(
        "docker",
        "inspect",
        "--format",
        "{{.State.Running}}",
        CONTAINER_NAME,
        check=False,
    )
    return result.returncode == 0 and result.stdout.strip() == "true"


def _container_health_status() -> str:
    result = _run(
        "docker",
        "inspect",
        "--format",
        "{{if .State.Health}}{{.State.Health.Status}}{{else}}missing{{end}}",
        CONTAINER_NAME,
        check=False,
    )
    return result.stdout.strip() if result.returncode == 0 else "not_found"


def _wait_for_container_health(timeout: float = 30) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        status = _container_health_status()
        if status == "healthy":
            return
        if status in {"unhealthy", "missing", "not_found"}:
            raise RuntimeError(f"container_health_failed:{status}")
        time.sleep(1)
    raise RuntimeError(f"container_health_timeout:{_container_health_status()}")


def _safe_failure_diagnostics() -> None:
    inspect = _run(
        "docker",
        "inspect",
        "--format",
        "{{json .State}}",
        CONTAINER_NAME,
        check=False,
    )
    if inspect.returncode == 0:
        try:
            state = json.loads(inspect.stdout)
            print(
                "SMOKE_STATE"
                f" status={state.get('Status', 'unknown')}"
                f" running={state.get('Running', False)}"
                f" exit_code={state.get('ExitCode', -1)}"
            )
        except (TypeError, ValueError):
            pass
    logs = _run("docker", "logs", CONTAINER_NAME, check=False)
    for line in (logs.stdout + logs.stderr).splitlines():
        if line.startswith(("STARTUP |", "PROCESS_EXIT |", "Startup error |", "Runtime error |")):
            print(line)


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: smoke_test_startup_container.py IMAGE", file=sys.stderr)
        return 2
    image = sys.argv[1]
    _run("docker", "rm", "-f", CONTAINER_NAME, check=False)
    try:
        _run(
            "docker",
            "run",
            "--detach",
            "--name",
            CONTAINER_NAME,
            "--publish",
            f"127.0.0.1:{HOST_PORT}:8080",
            "--health-start-period=0s",
            "--health-interval=1s",
            "--health-timeout=5s",
            "--health-retries=10",
            "--env",
            "ENVIRONMENT=test",
            "--env",
            "SESSION_SECRET_KEY=smoke-test-secret",
            # Deliberately unresolvable — see module docstring. get_auth_connection()
            # fails fast; GET /healthcheck must still return 200 either way.
            "--env",
            "AUTH_DB_HOST=eq10-smoke-test-unresolvable.invalid",
            "--env",
            "AUTH_DB_PORT=5432",
            "--env",
            "AUTH_DB_NAME=smoketest",
            "--env",
            "AUTH_DB_USER=smoketest",
            "--env",
            "AUTH_DB_PASSWORD=smoketest",
            "--env",
            "AUTH_DB_SSLMODE=disable",
            image,
        )
        _run("docker", "exec", CONTAINER_NAME, "sh", "-n", "/app/start_fastapi.sh")
        _run("docker", "exec", CONTAINER_NAME, "nginx", "-t")

        ping_body = _wait_for("/ping", 200)
        if json.loads(ping_body).get("status") != "ok":
            raise RuntimeError(f"ping_unexpected_body:{ping_body!r}")
        _wait_for_container_health()

        health_body = _wait_for("/healthcheck", 200)
        try:
            health_data = json.loads(health_body)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"healthcheck_body_not_json:{health_body!r}") from exc
        if "status" not in health_data:
            raise RuntimeError(f"healthcheck_missing_status_key:{health_body!r}")

        estatisticas_status, estatisticas_body = _request("/estatisticas")
        if estatisticas_status != 200 or b"Mamanguape" not in estatisticas_body:
            raise RuntimeError(f"estatisticas_unexpected_response:{estatisticas_status}")

        internal_probe = (
            "import socket;"
            "[socket.create_connection(('127.0.0.1',p),timeout=2).close() "
            "for p in (8811, 8080)]"
        )
        _run(
            "docker",
            "exec",
            CONTAINER_NAME,
            "/app/.venv/bin/python",
            "-c",
            internal_probe,
        )

        _signal_process("uvicorn")
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline and _container_running():
            time.sleep(1)
        if _container_running():
            raise RuntimeError("container_parent_remained_after_core_child_exit")

        state = json.loads(
            _run(
                "docker",
                "inspect",
                "--format",
                "{{json .State}}",
                CONTAINER_NAME,
            ).stdout
        )
        if state.get("ExitCode") == 0:
            raise RuntimeError("unexpected_zero_exit_after_core_child_exit")
        print("Startup container smoke test passed.")
        return 0
    except Exception:
        _safe_failure_diagnostics()
        raise
    finally:
        _run("docker", "rm", "-f", CONTAINER_NAME, check=False)


if __name__ == "__main__":
    raise SystemExit(main())

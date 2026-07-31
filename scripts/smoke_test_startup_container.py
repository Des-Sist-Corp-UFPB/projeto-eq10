"""Smoke test Linux/Docker do stack Streamlit + readiness + Nginx."""

from __future__ import annotations

import json
import subprocess
import sys
import time
import urllib.error
import urllib.request

CONTAINER_NAME = "eq10-startup-smoke"
HOST_PORT = 18080


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


def _signal_process(marker: str) -> None:
    code = (
        "import os,signal;"
        f"marker={marker!r}.encode();"
        "matches=[];"
        "\nfor name in os.listdir('/proc'):\n"
        "  if name.isdigit():\n"
        "    try:\n"
        "      cmd=open(f'/proc/{name}/cmdline','rb').read()\n"
        "      if marker in cmd: matches.append(int(name))\n"
        "    except OSError: pass\n"
        "\nif len(matches)!=1: raise SystemExit(3)\n"
        "os.kill(matches[0],signal.SIGTERM)"
    )
    _run("docker", "exec", CONTAINER_NAME, "/app/.venv/bin/python", "-c", code)


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
            "--env",
            "ENVIRONMENT=test",
            "--env",
            "AUTH_DATABASE_URL=sqlite+pysqlite:////tmp/readiness.sqlite3",
            image,
        )
        _run("docker", "exec", CONTAINER_NAME, "sh", "-n", "/app/start.sh")
        _run("docker", "exec", CONTAINER_NAME, "nginx", "-t")

        _wait_for("/ping", 200)
        health_body = _wait_for("/health", 200)
        if health_body != b'{"status":"healthy","database":"connected"}':
            raise RuntimeError("unexpected_healthy_body")

        internal_probe = (
            "import socket;"
            "[socket.create_connection(('127.0.0.1',p),timeout=2).close() "
            "for p in (8501,8502,8080)]"
        )
        _run(
            "docker",
            "exec",
            CONTAINER_NAME,
            "/app/.venv/bin/python",
            "-c",
            internal_probe,
        )

        _signal_process("src.diagnostics.readiness_server")
        _wait_for("/ping", 200)
        unavailable_body = _wait_for("/health", 503)
        if unavailable_body != b'{"status":"unhealthy","database":"unavailable"}':
            raise RuntimeError("unexpected_unhealthy_body")

        _signal_process("streamlit")
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

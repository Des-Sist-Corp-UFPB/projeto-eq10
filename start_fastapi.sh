#!/bin/sh
set -e

PYTHON="/app/.venv/bin/python"
UVICORN_PORT="8811"
NGINX_PORT="8080"
UVICORN_PID=""
NGINX_PID=""
UVICORN_PID_FILE="/tmp/eq10-uvicorn.pid"
NGINX_PID_FILE="/tmp/eq10-nginx.pid"

write_pid_file() {
  pid_file="$1"
  pid="$2"
  case "$pid" in
    ''|*[!0-9]*)
      echo "Startup error | component=supervisor | code=invalid_child_pid"
      exit 1
      ;;
  esac
  printf '%s\n' "$pid" > "$pid_file"
}

remove_pid_files() {
  rm -f "$UVICORN_PID_FILE" "$NGINX_PID_FILE"
}

remove_pid_files

if [ ! -x "$PYTHON" ]; then
  echo "Startup error | component=uvicorn | code=venv_python_missing"
  exit 1
fi

terminate() {
  for pid in "$NGINX_PID" "$UVICORN_PID"; do
    if [ -n "$pid" ]; then
      kill -TERM "$pid" 2>/dev/null || true
    fi
  done
  for pid in "$NGINX_PID" "$UVICORN_PID"; do
    if [ -n "$pid" ]; then
      wait "$pid" 2>/dev/null || true
    fi
  done
  remove_pid_files
}
trap terminate INT TERM EXIT

report_exit() {
  component="$1"
  pid="$2"
  set +e
  wait "$pid" 2>/dev/null
  exit_code=$?
  set -e
  echo "PROCESS_EXIT | component=${component} | exit_code=${exit_code}"
}

echo "STARTUP | component=uvicorn | status=starting"
# --proxy-headers + --forwarded-allow-ips: trust X-Forwarded-Proto/-For from nginx
# (same container, connects via 127.0.0.1) so request.url_for() and friends reflect
# the real end-to-end scheme when an outer TLS-terminating proxy is in front of us.
"$PYTHON" -m uvicorn app.main:app \
  --host 127.0.0.1 \
  --port "$UVICORN_PORT" \
  --workers 2 \
  --proxy-headers \
  --forwarded-allow-ips="127.0.0.1" \
  --no-access-log &
UVICORN_PID=$!
write_pid_file "$UVICORN_PID_FILE" "$UVICORN_PID"

attempt=0
while [ "$attempt" -lt 30 ]; do
  if ! kill -0 "$UVICORN_PID" 2>/dev/null; then
    report_exit "uvicorn" "$UVICORN_PID"
    echo "Startup error | component=uvicorn | code=crashed_before_ready"
    exit 1
  fi
  if "$PYTHON" -c \
    "import socket; s=socket.create_connection(('127.0.0.1', ${UVICORN_PORT}), timeout=1); s.close()" \
    2>/dev/null; then
    break
  fi
  attempt=$((attempt + 1))
  sleep 1
done

echo "STARTUP | component=uvicorn | status=listening | port=${UVICORN_PORT}"

echo "STARTUP | component=nginx | status=starting"
nginx -g "daemon off;" &
NGINX_PID=$!
write_pid_file "$NGINX_PID_FILE" "$NGINX_PID"

attempt=0
while [ "$attempt" -lt 10 ]; do
  if ! kill -0 "$NGINX_PID" 2>/dev/null; then
    report_exit "nginx" "$NGINX_PID"
    echo "Startup error | component=nginx | code=crashed_before_ready"
    exit 1
  fi
  if "$PYTHON" -c \
    "import socket; s=socket.create_connection(('127.0.0.1', ${NGINX_PORT}), timeout=1); s.close()" \
    2>/dev/null; then
    break
  fi
  attempt=$((attempt + 1))
  sleep 1
done
echo "STARTUP | component=nginx | status=listening | port=${NGINX_PORT}"

# O loop portavel supervisiona os dois processos; o trap encerra o outro assim
# que qualquer um dos dois termina.
while :; do
  if ! kill -0 "$UVICORN_PID" 2>/dev/null; then
    report_exit "uvicorn" "$UVICORN_PID"
    exit 1
  fi
  if ! kill -0 "$NGINX_PID" 2>/dev/null; then
    report_exit "nginx" "$NGINX_PID"
    exit 1
  fi
  sleep 2
done

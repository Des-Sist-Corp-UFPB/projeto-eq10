#!/bin/sh
set -e

PYTHON="/app/.venv/bin/python"
UVICORN_PORT="8811"
NGINX_PORT="8080"

if [ ! -x "$PYTHON" ]; then
  echo "Startup error | component=uvicorn | code=venv_python_missing"
  exit 1
fi

terminate() {
  kill -TERM "$UVICORN_PID" 2>/dev/null || true
  kill -TERM "$NGINX_PID" 2>/dev/null || true
  wait "$UVICORN_PID" 2>/dev/null || true
  wait "$NGINX_PID" 2>/dev/null || true
}
trap terminate INT TERM EXIT

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

attempt=0
while [ "$attempt" -lt 30 ]; do
  if ! kill -0 "$UVICORN_PID" 2>/dev/null; then
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

attempt=0
while [ "$attempt" -lt 10 ]; do
  if ! kill -0 "$NGINX_PID" 2>/dev/null; then
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

while :; do
  if ! kill -0 "$UVICORN_PID" 2>/dev/null; then
    echo "PROCESS_EXIT | component=uvicorn"
    exit 1
  fi
  if ! kill -0 "$NGINX_PID" 2>/dev/null; then
    echo "PROCESS_EXIT | component=nginx"
    exit 1
  fi
  sleep 2
done

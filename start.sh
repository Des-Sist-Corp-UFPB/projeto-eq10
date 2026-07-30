#!/bin/sh
set -e

STREAMLIT_PYTHON="/app/.venv/bin/python"
STREAMLIT_APP="app_ai_chat.py"
STREAMLIT_PORT="8501"
READINESS_PORT="8502"
NGINX_PORT="8080"
READINESS_PID=""
STREAMLIT_PID=""
NGINX_PID=""

if [ ! -x "$STREAMLIT_PYTHON" ]; then
  echo "Startup error | component=streamlit | code=venv_python_missing"
  exit 1
fi

if [ ! -f "$STREAMLIT_APP" ]; then
  echo "Startup error | component=streamlit | code=entrypoint_missing"
  exit 1
fi

terminate() {
  for pid in "$NGINX_PID" "$STREAMLIT_PID" "$READINESS_PID"; do
    if [ -n "$pid" ]; then
      kill -TERM "$pid" 2>/dev/null || true
    fi
  done
  for pid in "$NGINX_PID" "$STREAMLIT_PID" "$READINESS_PID"; do
    if [ -n "$pid" ]; then
      wait "$pid" 2>/dev/null || true
    fi
  done
}
trap terminate INT TERM EXIT

echo "Startup diagnostics | component=readiness | address=loopback | port=${READINESS_PORT}"
"$STREAMLIT_PYTHON" -m src.diagnostics.readiness_server &
READINESS_PID=$!

echo "Startup diagnostics | component=streamlit | address=0.0.0.0 | port=${STREAMLIT_PORT}"
"$STREAMLIT_PYTHON" -m streamlit run "$STREAMLIT_APP" \
  --server.address=0.0.0.0 \
  --server.port="${STREAMLIT_PORT}" \
  --server.headless=true &
STREAMLIT_PID=$!

echo "Startup diagnostics | component=nginx | port=${NGINX_PORT} | upstream=127.0.0.1:${STREAMLIT_PORT}"

# Nginx so passa a aceitar trafego quando os dois sockets internos existem.
STREAMLIT_READY=false
attempt=0
while [ "$attempt" -lt 60 ]; do
  if ! kill -0 "$STREAMLIT_PID" 2>/dev/null || ! kill -0 "$READINESS_PID" 2>/dev/null; then
    echo "Startup error | component=process_supervisor | code=child_exited"
    exit 1
  fi
  if "$STREAMLIT_PYTHON" -c "import socket; s=socket.create_connection(('127.0.0.1', ${STREAMLIT_PORT}), timeout=1); s.close()" 2>/dev/null; then
    STREAMLIT_READY=true
    break
  fi
  attempt=$((attempt + 1))
  sleep 1
done

if [ "$STREAMLIT_READY" != "true" ]; then
  echo "Startup error | component=streamlit | code=listen_timeout"
  exit 1
fi
echo "Startup diagnostics | component=streamlit | status=listening"

if ! "$STREAMLIT_PYTHON" -c "import socket; s=socket.create_connection(('127.0.0.1', ${READINESS_PORT}), timeout=2); s.close()" 2>/dev/null; then
  echo "Startup error | component=readiness | code=listen_timeout"
  exit 1
fi
echo "Startup diagnostics | component=readiness | status=listening"

nginx -g "daemon off;" &
NGINX_PID=$!
echo "Startup diagnostics | component=nginx | status=listening"

# O loop portavel supervisiona os tres processos; o trap encerra os demais
# assim que qualquer filho termina.
while :; do
  for pid in "$READINESS_PID" "$STREAMLIT_PID" "$NGINX_PID"; do
    if ! kill -0 "$pid" 2>/dev/null; then
      echo "Runtime error | component=process_supervisor | code=child_exited"
      exit 1
    fi
  done
  sleep 1
done

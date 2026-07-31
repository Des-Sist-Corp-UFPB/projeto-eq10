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

report_exit() {
  component="$1"
  pid="$2"
  set +e
  wait "$pid" 2>/dev/null
  exit_code=$?
  set -e
  echo "PROCESS_EXIT | component=${component} | exit_code=${exit_code}"
}

echo "STARTUP | stage=readiness_start | status=starting"
"$STREAMLIT_PYTHON" -m src.diagnostics.readiness_server &
READINESS_PID=$!

echo "STARTUP | stage=streamlit_start | status=starting"
"$STREAMLIT_PYTHON" -m streamlit run "$STREAMLIT_APP" \
  --server.address=0.0.0.0 \
  --server.port="${STREAMLIT_PORT}" \
  --server.headless=true &
STREAMLIT_PID=$!

# Nginx so passa a aceitar trafego quando o socket do Streamlit existe.
STREAMLIT_READY=false
attempt=0
while [ "$attempt" -lt 60 ]; do
  if ! kill -0 "$STREAMLIT_PID" 2>/dev/null; then
    report_exit "streamlit" "$STREAMLIT_PID"
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
echo "STARTUP | stage=streamlit_start | status=listening"

if kill -0 "$READINESS_PID" 2>/dev/null && \
  "$STREAMLIT_PYTHON" -c "import socket; s=socket.create_connection(('127.0.0.1', ${READINESS_PORT}), timeout=2); s.close()" 2>/dev/null; then
  echo "STARTUP | stage=readiness_start | status=listening"
else
  if kill -0 "$READINESS_PID" 2>/dev/null; then
    kill -TERM "$READINESS_PID" 2>/dev/null || true
    report_exit "readiness" "$READINESS_PID"
  else
    report_exit "readiness" "$READINESS_PID"
  fi
  READINESS_PID=""
  echo "STARTUP | stage=readiness_start | status=unavailable"
fi

echo "STARTUP | stage=nginx_start | status=starting"
nginx -g "daemon off;" &
NGINX_PID=$!

NGINX_READY=false
attempt=0
while [ "$attempt" -lt 10 ]; do
  if ! kill -0 "$NGINX_PID" 2>/dev/null; then
    report_exit "nginx" "$NGINX_PID"
    exit 1
  fi
  if "$STREAMLIT_PYTHON" -c "import socket; s=socket.create_connection(('127.0.0.1', ${NGINX_PORT}), timeout=1); s.close()" 2>/dev/null; then
    NGINX_READY=true
    break
  fi
  attempt=$((attempt + 1))
  sleep 1
done

if [ "$NGINX_READY" != "true" ]; then
  echo "Startup error | component=nginx | code=listen_timeout"
  exit 1
fi
echo "STARTUP | stage=nginx_start | status=listening"

# O loop portavel supervisiona os tres processos; o trap encerra os demais
# assim que qualquer filho termina.
while :; do
  if ! kill -0 "$STREAMLIT_PID" 2>/dev/null; then
    report_exit "streamlit" "$STREAMLIT_PID"
    exit 1
  fi
  if ! kill -0 "$NGINX_PID" 2>/dev/null; then
    report_exit "nginx" "$NGINX_PID"
    exit 1
  fi
  if [ -n "$READINESS_PID" ] && ! kill -0 "$READINESS_PID" 2>/dev/null; then
    report_exit "readiness" "$READINESS_PID"
    READINESS_PID=""
  fi
  sleep 1
done

#!/bin/sh
set -e

STREAMLIT_PYTHON="/app/.venv/bin/python"
STREAMLIT_APP="app_ai_chat.py"
STREAMLIT_PORT="8501"
NGINX_PORT="8080"

if [ ! -x "$STREAMLIT_PYTHON" ]; then
  echo "Startup error | component=streamlit | code=venv_python_missing"
  exit 1
fi

if [ ! -f "$STREAMLIT_APP" ]; then
  echo "Startup error | component=streamlit | code=entrypoint_missing"
  exit 1
fi

echo "Startup diagnostics | component=streamlit | address=0.0.0.0 | port=${STREAMLIT_PORT}"
echo "Startup diagnostics | component=nginx | port=${NGINX_PORT} | upstream=127.0.0.1:${STREAMLIT_PORT}"

"$STREAMLIT_PYTHON" -m streamlit run "$STREAMLIT_APP" \
  --server.address=0.0.0.0 \
  --server.port="${STREAMLIT_PORT}" \
  --server.headless=true &
STREAMLIT_PID=$!

terminate() {
  kill -TERM "$STREAMLIT_PID" 2>/dev/null || true
  wait "$STREAMLIT_PID" 2>/dev/null || true
}
trap terminate INT TERM

# Nginx so passa a aceitar trafego quando o socket do Streamlit estiver pronto.
# Isso elimina os erros esperados de connection refused durante o bootstrap.
READY=false
attempt=0
while [ "$attempt" -lt 60 ]; do
  if ! kill -0 "$STREAMLIT_PID" 2>/dev/null; then
    wait "$STREAMLIT_PID"
    exit $?
  fi
  if "$STREAMLIT_PYTHON" -c "import socket; s=socket.create_connection(('127.0.0.1', ${STREAMLIT_PORT}), timeout=1); s.close()" 2>/dev/null; then
    READY=true
    break
  fi
  attempt=$((attempt + 1))
  sleep 1
done

if [ "$READY" != "true" ]; then
  echo "Startup error | component=streamlit | code=listen_timeout"
  terminate
  exit 1
fi

echo "Startup diagnostics | component=streamlit | status=listening"
nginx
wait "$STREAMLIT_PID"

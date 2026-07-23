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

nginx

exec "$STREAMLIT_PYTHON" -m streamlit run "$STREAMLIT_APP" \
  --server.address=0.0.0.0 \
  --server.port="${STREAMLIT_PORT}" \
  --server.headless=true

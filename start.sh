#!/bin/bash
set -Eeuo pipefail

STREAMLIT_PORT="8501"
NGINX_PORT="8080"

echo "Startup diagnostics | component=streamlit | address=0.0.0.0 | port=${STREAMLIT_PORT}"
echo "Startup diagnostics | component=nginx | port=${NGINX_PORT} | upstream=127.0.0.1:${STREAMLIT_PORT}"

python -m streamlit run app_ai_chat.py \
  --server.address=0.0.0.0 \
  --server.port="${STREAMLIT_PORT}" \
  --server.headless=true &
streamlit_pid=$!

nginx -g 'daemon off;' &
nginx_pid=$!

cleanup() {
  kill "${streamlit_pid}" "${nginx_pid}" 2>/dev/null || true
}

trap cleanup EXIT

set +e
wait -n "${streamlit_pid}" "${nginx_pid}"
exit_code=$?
set -e
cleanup
exit "${exit_code}"

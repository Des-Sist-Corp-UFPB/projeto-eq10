#!/bin/bash

# Iniciar o Streamlit em background na porta interna 8501 (fechada para a rede do professor)
python -m streamlit run app_ai_chat.py --server.address=127.0.0.1 --server.port=8501 &

# Iniciar o Nginx em foreground na porta 8080 (a porta que o professor mapeia)
nginx -g 'daemon off;'

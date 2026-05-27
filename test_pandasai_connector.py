import os
from src.ai.read_only_datasus import get_readonly_engine
from pandasai_litellm.litellm import LiteLLM
import pandasai as pai

try:
    from pandasai.connectors import PostgreSQLConnector
    print("PostgreSQLConnector is available.")
except ImportError:
    print("PostgreSQLConnector is NOT available.")


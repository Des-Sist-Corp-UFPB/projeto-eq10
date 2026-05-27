from src.ai.datasus_ai import perguntar_datasus
import sys
try:
    print(perguntar_datasus("Total de valor aprovado por município"))
except Exception as e:
    print("FATAL:", e)

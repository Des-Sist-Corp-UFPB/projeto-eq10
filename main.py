from pysus.online_data.SIA import SIA
import pandas as pd
from datetime import datetime
from src.extract import extract_data
from src.transform import transform
from pathlib import Path

sia = SIA().load()


BASE_DIR = Path(__file__).resolve().parent
file_path = BASE_DIR / "data" / "sia_datasus.parquet"


if __name__ == "__main__":
    print("Iniciando ETL")
    extract_data(sia)
    print("Extração feita com sucesso")
    df = transform(file_path)
    df.to_parquet(file_path, index=False)
    print("ETL feito com sucesso!")
    print(df.head())

    


from pysus.online_data.SIA import SIA
import pandas as pd
from datetime import datetime
from src.extract import extract_data
from src.transform import transform
from pathlib import Path
from src.load import load_data_sus

sia = SIA().load()


BASE_DIR = Path(__file__).resolve().parent
file_path = BASE_DIR / "data" / "sia_datasus.parquet"
file_path_to_save = BASE_DIR / "data"/ "sia_datasus_transformed.parquet"
file_path_to_save_ocupacao = BASE_DIR / "data"/ "dim_ocupacao.parquet"
file_path_to_save_procedimentos = BASE_DIR / "data"/ "dim_procedimentos.parquet"

if __name__ == "__main__":
    df_ocupacao = pd.read_parquet(file_path_to_save_ocupacao, engine = "pyarrow")
    df_procedimentos = pd.read_parquet(file_path_to_save_procedimentos, engine = "pyarrow")
    load_data_sus('dim_procedimento', df_procedimentos)
    load_data_sus('dim_ocupacao', df_ocupacao)
    print("ETL feito com sucesso!")
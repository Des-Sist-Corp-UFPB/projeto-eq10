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
file_path_to_save_raca_cor = BASE_DIR / "data"/ "dim_raca_cor.parquet"
file_path_to_save_municipio = BASE_DIR / "data"/ "dim_municipio.parquet"

if __name__ == "__main__":
    df_ocupacao = pd.read_parquet(file_path_to_save_ocupacao, engine = "pyarrow")
    df_procedimentos = pd.read_parquet(file_path_to_save_procedimentos, engine = "pyarrow")
    df_raca_cor = pd.read_parquet(file_path_to_save_raca_cor, engine = "pyarrow")
    df_municipios = pd.read_parquet(file_path_to_save_municipio, engine = "pyarrow")
    load_data_sus('dim_procedimento', df_procedimentos)
    load_data_sus('dim_ocupacao', df_ocupacao)
    load_data_sus('dim_raca_cor', df_raca_cor)
    load_data_sus('dim_municipio', df_municipios)
    print("ETL feito com sucesso!")
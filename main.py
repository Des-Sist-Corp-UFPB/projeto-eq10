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

if __name__ == "__main__":
    print("Iniciando ETL")
    extract_data(sia)
    print("Extração feita com sucesso")
    df = transform_datasus(file_path)
    df.to_parquet(file_path_to_save, index=False)
    df = pd.read_parquet(file_path_to_save, engine = "pyarrow")
    load_data_sus('data_sus', df)
    print("ETL feito com sucesso!")



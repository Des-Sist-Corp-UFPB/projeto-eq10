from pysus.online_data.SIA import SIA
import pandas as pd
from datetime import datetime
from src.extract import extract_data
from src.transform import transform_remove_columns
from pathlib import Path

sia = SIA().load()


BASE_DIR = Path(__file__).resolve().parent
file_path = BASE_DIR / "data" / "sia_datasus.parquet"


if __name__ == "__main__":
    extract_data(sia)
    df = transform_remove_columns(file_path)
    print(df.head())



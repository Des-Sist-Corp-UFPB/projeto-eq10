from datetime import datetime, timedelta
from airflow.decorators import dag, task
from pysus.online_data.SIA import SIA
from pathlib import Path
import sys
import os

sys.path.insert(0, '/opt/airflow/src')

from src.extract import extract_data
from src.load import load_data_sus
from src.transform import transform_datasus
from dotenv import load_dotenv

sia = SIA().load()
file_path = '/opt/airflow/data/sia_datasus.parquet'

env_path = Path(__file__).resolve().parent.parent / 'config' / '.env'
load_dotenv(env_path)

@dag(
    dag_id='datasus_etl',
    default_args={
        'owner': 'airflow',
        'depends_on_past': False,
        'retries': 3,
        'retry_delay': timedelta(minutes=1),
    },
    description='ETL para dados do Datasus',
    schedule="0 12-23 25-31 * *",        
    start_date=datetime(2026, 4, 25),     
    catchup=False,                        
    tags=['datasus', 'etl', 'sia']
)

def datasus_etl():
    
    @task
    def extract():
        extract_data(sia)
        
    @task
    def transform():
        df = transform_datasus(file_path)
        df.to_parquet('/opt/airflow/data/sia_datasus_transformed.parquet', index=False)
        
    @task 
    def load():
        import pandas as pd
        df = pd.read_parquet('/opt/airflow/data/sia_datasus_transformed.parquet')
        load_data_sus('data_sus', df)
        
    extract() >> transform() >> load()
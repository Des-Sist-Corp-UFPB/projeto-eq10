import pandas as pd
from pathlib import Path
import pyarrow
import sys
import os

import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)

logger = logging.getLogger(__name__)


from constants.constants import (
    LIST_FILTER_CITIES,
    LIST_FILTER_COLUMNS,
    DIC_RENAME_COLUMNS,
    DIC_COLUMNS_TYPE,
    LIST_UNITS
)

# Função responsável por ler o arquivo parquet e já selecionar apenas as colunas necessárias
def transform_remove_columns(file_path) -> pd.DataFrame:
    logger.info(f"Lendo arquivo: {file_path}")
    
    df = pd.read_parquet(file_path, engine="pyarrow", columns=LIST_FILTER_COLUMNS)
    
    logger.info(f"Arquivo lido com sucesso | Linhas: {len(df)} | Colunas: {len(df.columns)}")
    
    return df


# Função responsável por renomear as colunas do DataFrame
def transform_rename_columns(df) -> pd.DataFrame:
    logger.info("Renomeando colunas")
    return df.rename(columns=DIC_RENAME_COLUMNS)


# Função para filtrar apenas os municípios desejados
def transform_filter_city(df) -> pd.DataFrame:
    before = len(df)
    
    df = df[df["cod_municipio_atendido"].isin(LIST_FILTER_CITIES)]
    
    after = len(df)
    logger.info(f"Filtro cidades aplicado | Antes: {before} | Depois: {after}")
    
    return df

# Função para filtrar apenas as unidades (CNES) desejadas
def transform_filter_units(df) -> pd.DataFrame:
    before = len(df)
    
    df = df[df["cod_unidade"].isin(LIST_UNITS)]
    
    after = len(df)
    logger.info(f"Filtro unidades aplicado | Antes: {before} | Depois: {after}")
    
    return df

# Função para corrigir os tipos das colunas conforme definido no dicionário
def transform_fix_types(df):
    logger.info("Ajustando tipos de dados")
    
    df = df.copy()
    
    for k, v in DIC_COLUMNS_TYPE.items():
        if k == "int":
            for coluna in v:
                df[coluna] = df[coluna].astype(int)
        
        elif k == "float":
            for coluna in v:
                df[coluna] = df[coluna].astype(float)
        
        elif k == "datetime":
            for coluna in v:
                df[coluna] = pd.to_datetime(df[coluna], format="%Y%m")
    
    logger.info("Tipos ajustados com sucesso")
    
    return df


# Função principal que executa toda a pipeline de transformação (ETL - parte de transformação)
def transform_datasus(file_path):
    logger.info("Iniciando transformação de dados")

    df = transform_remove_columns(file_path)
    df = transform_rename_columns(df)
    df = transform_filter_city(df)
    df = transform_filter_units(df)
    df = transform_fix_types(df)

    logger.info(f"Transformação finalizada | Linhas finais: {len(df)}")

    return df
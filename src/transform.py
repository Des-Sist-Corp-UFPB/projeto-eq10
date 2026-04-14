import pandas as pd
from pathlib import Path
import pyarrow
from constants.constants import LIST_FILTER_CITIES, LIST_FILTER_COLUMNS, DIC_RENAME_COLUMNS, DIC_COLUMNS_TYPE, LIST_UNITS

# Função responsável por ler o arquivo parquet e já selecionar apenas as colunas necessárias
def transform_remove_columns(file_path) -> pd.DataFrame:
    df = pd.read_parquet(file_path, engine="pyarrow", columns=LIST_FILTER_COLUMNS)
    return df


# Função responsável por renomear as colunas do DataFrame
def transform_rename_columns(df) -> pd.DataFrame:
    df = df.rename(columns=DIC_RENAME_COLUMNS)
    return df


# Função para filtrar apenas os municípios desejados
def transform_filter_city(df) -> pd.DataFrame:
    df = df[df["municipio_atendido"].isin(LIST_FILTER_CITIES)]
    return df


# Função para filtrar apenas as unidades (CNES) desejadas
def transform_filter_units(df) -> pd.DataFrame:
    df = df[df["cnes"].isin(LIST_UNITS)]
    return df


# Função para corrigir os tipos das colunas conforme definido no dicionário
def transform_fix_types(df):
    # Cria uma cópia do DataFrame para evitar problemas de SettingWithCopyWarning
    df = df.copy()
    
    # Itera sobre o dicionário de tipos
    for k, v in DIC_COLUMNS_TYPE.items():
        
        # Conversão para inteiro
        if k == "int":
            for coluna in v:
                df[coluna] = df[coluna].astype(int)
        
        # Conversão para float
        elif k == "float":
            for coluna in v:
                df[coluna] = df[coluna].astype(float)
        
        # Conversão para datetime (formato YYYYMM → vira YYYY-MM-01)
        elif k == "datetime":
            for coluna in v:
                df[coluna] = pd.to_datetime(df[coluna], format="%Y%m")
    
    return df


# Função principal que executa toda a pipeline de transformação (ETL - parte de transformação)
def transform(file_path):
    # Leitura e seleção de colunas
    df = transform_remove_columns(file_path)
    
    # Renomeação das colunas
    df = transform_rename_columns(df)
    
    # Filtro por municípios
    df = transform_filter_city(df)
    
    # Filtro por unidades (CNES)
    df = transform_filter_units(df)
    
    # Ajuste dos tipos de dados
    df = transform_fix_types(df)
    
    # Retorna o DataFrame final tratado
    return df
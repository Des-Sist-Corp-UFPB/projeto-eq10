import pandas as pd
from pathlib import Path
import pyarrow

# Lista de municípios que serão filtrados (código IBGE)
# "250150": Bananeiras
# "251250": Queimadas
# "250890": Mamanguape
list_filter_cities = ["250150", "251250", "250890"]

# Lista de unidades de saúde (CNES) que serão mantidas no DataFrame
list_units = ["2597349", "7176295", "7654553", "5427207", "5489822", "3769593", 
              "0840386", "2932709", "5906822", "8095973", "8077576", "8077584", 
              "2871467", "7173814", "6389082", "0617342", "3941108", "091023", 
              "2418703", "2418711", "4333640", "7157002", "6910327", "5103916",
              "4787994","2341212","2908247","6199194","7021747","6924611","6859011"]

# Lista de colunas que serão lidas do arquivo parquet (reduz uso de memória e melhora performance)
list_filter_columns = ["PA_QTDAPR", "PA_QTDPRO", "PA_VALAPR", "PA_VALPRO", "PA_UFMUN", "PA_MUNPCN", 
                        "PA_MVM", "PA_RACACOR", "PA_IDADE", "PA_CODUNI", "PA_CBOCOD", "PA_PROC_ID"]

# Dicionário para renomear as colunas do padrão original (DataSUS) para nomes mais amigáveis
dic_rename_columns = {
    "PA_QTDAPR" : "frequencia",
    "PA_QTDPRO" : "quantidade_apresentada",
    "PA_VALAPR" : "valor_aprovado",
    "PA_VALPRO" : "valor_apresentado",
    "PA_UFMUN" : "municipio_atendido",
    "PA_MUNPCN" : "municipio_residencia",
    "PA_MVM" : "data",
    "PA_RACACOR" : "raca_cor",
    "PA_IDADE" : "idade",
    "PA_CODUNI" : "cnes",
    "PA_CBOCOD" : "codigo_brasileiro_ocupacao",
    "PA_PROC_ID" : "codigo_procedimento"
}

# Dicionário que define os tipos de dados esperados para cada coluna após transformação
dicionario_colunas = {
    "int" : ["frequencia", "quantidade_apresentada", "idade"],
    "float" : ["valor_aprovado", "valor_apresentado"],
    "datetime" : ["data"]
}


# Função responsável por ler o arquivo parquet e já selecionar apenas as colunas necessárias
def transform_remove_columns(file_path) -> pd.DataFrame:
    df = pd.read_parquet(file_path, engine="pyarrow", columns=list_filter_columns)
    return df


# Função responsável por renomear as colunas do DataFrame
def transform_rename_columns(df) -> pd.DataFrame:
    df = df.rename(columns=dic_rename_columns)
    return df


# Função para filtrar apenas os municípios desejados
def transform_filter_city(df) -> pd.DataFrame:
    df = df[df["municipio_atendido"].isin(list_filter_cities)]
    return df


# Função para filtrar apenas as unidades (CNES) desejadas
def transform_filter_units(df) -> pd.DataFrame:
    df = df[df["cnes"].isin(list_units)]
    return df


# Função para corrigir os tipos das colunas conforme definido no dicionário
def transform_fix_types(df):
    # Cria uma cópia do DataFrame para evitar problemas de SettingWithCopyWarning
    df = df.copy()
    
    # Itera sobre o dicionário de tipos
    for k, v in dicionario_colunas.items():
        
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
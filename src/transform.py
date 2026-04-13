import pandas as pd
from pathlib import Path
import pyarrow

list_filter_cities = ["250150", "251250", "250890"] # "250150": "Bananeiras"/ "251250": "Queimadas"/ "250890": "Mamanguape",

list_units = ["2597349", "7176295", "7654553", "5427207", "5489822", "3769593", 
              "0840386", "2932709", "5906822", "8095973", "8077576", "8077584", 
              "2871467", "7173814", "6389082", "0617342", "3941108", "091023", 
              "2418703", "2418711", "4333640", "7157002", "6910327", "5103916",
              "4787994","2341212","2908247","6199194","7021747","6924611","6859011"]

list_filter_columns = ["PA_QTDAPR", "PA_QTDPRO", "PA_VALAPR", "PA_VALPRO", "PA_UFMUN", "PA_MUNPCN", 
                        "PA_MVM", "PA_RACACOR", "PA_IDADE", "PA_CODUNI", "PA_CBOCOD", "PA_PROC_ID"]

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

def transform_remove_columns(file_path) -> pd.DataFrame:
    df = pd.read_parquet(file_path, engine="pyarrow", columns=list_filter_columns)
    return df

def transform_rename_columns(df) -> pd.DataFrame:
    df = df.rename(columns=dic_rename_columns)
    return df

def transform_filter_city(df) -> pd.DataFrame:
    df = df[df["municipio_atendido"].isin(list_filter_cities)]
    if(len(list_filter_cities) == len(df["municipio_atendido"].unique())):
        return df
    
def transform_filter_units(df) -> pd.DataFrame:
    df = df[df["cnes"].isin(list_units)]
    if(len(df["cnes"].unique()) <= len(list_units)):
        return df



import pandas as pd
from pathlib import Path
import pyarrow

lista_filtros_cidades = ["250150", "251250", "250890"] # "250150": "Bananeiras"/ "251250": "Queimadas"/ "250890": "Mamanguape",

list_units = ["2597349", "7176295", "7654553", "5427207", "5489822", "3769593", "0840386", "2932709", "5906822", "8095973", "8077576", "8077584", "2871467", "7173814", "6389082", "0617342"]

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
    df = pd.read_parquet(file_path, engine="pyarrow", columns=["PA_QTDAPR", "PA_QTDPRO", "PA_VALAPR", "PA_VALPRO", "PA_UFMUN", "PA_MUNPCN", 
                                                                            "PA_MVM", "PA_RACACOR", "PA_IDADE", "PA_CODUNI", "PA_CBOCOD", "PA_PROC_ID"])
    return df

def transform_rename_columns(df) -> pd.DataFrame:
    df = df.rename(columns=dic_rename_columns)
    return df

def transform_filter_city(df) -> pd.DataFrame:
    df = df[df["PA_UFMUN"].isin(lista_filtros_cidades)]
    if(len(lista_filtros_cidades) == len(df["PA_UFMUN"].unique())):
        return df
    
def transform_filter_units(df) -> pd.DataFrame:
    df = df[df["PA_CODUNI"].isin(list_units)]
    if(len(list_units) == len(df["PA_CODUNI"].unique())):
        return df

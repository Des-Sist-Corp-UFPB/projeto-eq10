import pandas as pd
from pathlib import Path
import pyarrow

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


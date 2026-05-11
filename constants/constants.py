
# Lista de municípios que serão filtrados (código IBGE)
# "250150": Bananeiras
# "251250": Queimadas
# "250890": Mamanguape
LIST_FILTER_CITIES = ["250150", "251250", "250890"]

# Lista de unidades (CNES)
LIST_UNITS = [
    "2597349", "7176295", "7654553", "5427207", "5489822", "3769593", 
    "0840386", "2932709", "5906822", "8095973", "8077576", "8077584", 
    "2871467", "7173814", "6389082", "0617342", "3941108", "091023", 
    "2418703", "2418711", "4333640", "7157002", "6910327", "5103916",
    "4787994","2341212","2908247","6199194","7021747","6924611","6859011"
]

# Colunas filtradas
LIST_FILTER_COLUMNS = [
    "PA_QTDAPR", "PA_QTDPRO", "PA_VALAPR", "PA_VALPRO", "PA_UFMUN", "PA_MUNPCN", 
    "PA_MVM", "PA_RACACOR", "PA_IDADE", "PA_CODUNI", "PA_CBOCOD", "PA_PROC_ID", "PA_SEXO"
]

		

# Rename
DIC_RENAME_COLUMNS = {
    "PA_QTDAPR": "frequencia",
    "PA_QTDPRO": "quantidade_apresentada",
    "PA_VALAPR": "valor_aprovado",
    "PA_VALPRO": "valor_apresentado",
    "PA_UFMUN": "cod_municipio_atendido",
    "PA_MUNPCN": "cod_municipio_residencia",
    "PA_MVM": "data",
    "PA_RACACOR": "cod_raca_cor",
    "PA_IDADE": "idade",
    "PA_CODUNI": "cod_unidade",
    "PA_CBOCOD": "cod_ocupacao",
    "PA_PROC_ID": "cod_procedimento",
    "PA_SEXO" : "sexo"
}

# Tipagem
DIC_COLUMNS_TYPE = {
    "int": ["frequencia", "quantidade_apresentada", "idade"],
    "float": ["valor_aprovado", "valor_apresentado"],
    "datetime": ["data"]
}
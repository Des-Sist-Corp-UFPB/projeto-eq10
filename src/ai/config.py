"""Configuracoes seguras da camada de IA."""

AI_MAX_MONTHS = 3
AI_MAX_ROWS = 5000000
AI_DATA_SOURCE = "vw_data_sus_ia"
AI_ALLOWED_TABLES = [AI_DATA_SOURCE]
AI_ALLOWED_COLUMNS = [
    "data",
    "idade",
    "sexo",
    "municipio_atendimento",
    "municipio_residencia",
    "raca_cor",
    "unidade",
    "ocupacao",
    "procedimento",
    "frequencia",
    "quantidade_apresentada",
    "valor_apresentado",
    "valor_aprovado",
]

# Importa ferramentas do SQLAlchemy para criar conexão com banco e executar queries SQL
from sqlalchemy import create_engine, text

# Função para codificar a senha na URL de conexão (evita problemas com caracteres especiais)
from urllib.parse import quote_plus

# Biblioteca para acessar variáveis de ambiente do sistema
import os

# Manipulação de caminhos de arquivos de forma segura
from pathlib import Path

# Biblioteca para manipulação de dados em formato de tabela (DataFrame)
import pandas as pd

# Carrega variáveis de ambiente a partir de um arquivo .env
from dotenv import load_dotenv

# Configuração de logs para acompanhar execução do código
import logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Define o caminho do arquivo .env (subindo dois níveis e acessando /config/.env)
env_path = Path(__file__).resolve().parent.parent / 'config' / '.env'

# Carrega as variáveis de ambiente do arquivo especificado
load_dotenv(env_path)

# Obtém o usuário do banco a partir das variáveis de ambiente
user = os.getenv('user')

# Obtém a senha do banco a partir das variáveis de ambiente
password = os.getenv('password')

# Obtém o nome do banco de dados
database = os.getenv('database')

# Host alternativo usado em ambientes Docker (comentado)
#host = 'host.docker.internal'

# Define o host como localhost (conexão local)
host = 'localhost'

# Função responsável por criar e retornar o engine de conexão com o PostgreSQL
def get_engine():
    # Log informando tentativa de conexão
    logging.info(f"→ Conectando em {host}:5432/{database}")
    
    # Cria e retorna o engine usando SQLAlchemy
    return create_engine(
        f"postgresql+psycopg2://{user}:{quote_plus(password)}@{host}:5432/{database}"
    )
    
# Cria o engine chamando a função
engine = get_engine()

# Função para carregar dados de um DataFrame para uma tabela no banco
def load_data_sus(table_name:str, df):
    
    # Insere os dados no banco usando pandas
    df.to_sql(
        name=table_name,      # Nome da tabela destino
        con=engine,           # Conexão com o banco
        if_exists='append',   # Adiciona os dados sem apagar os existentes
        index=False           # Não envia o índice do DataFrame
    )
    
    # Log informando sucesso no carregamento
    logging.info(f"✅ Dados carregados com sucesso!\n") 
    
    # Consulta todos os dados da tabela para verificação
    df_check = pd.read_sql(f'SELECT * FROM {table_name}', con=engine)
    
    # Log mostrando a quantidade total de registros após inserção
    logging.info(f"Total de registros na tabela: {len(df_check)}\n")
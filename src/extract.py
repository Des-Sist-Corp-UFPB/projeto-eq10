import pandas as pd
from pysus.online_data.SIA import SIA
from datetime import datetime
from pathlib import Path


# Função responsável por extrair os dados do SIA (DataSUS)
def extract_data(sia) -> Path:
    
    # Obtém a lista de arquivos disponíveis e pega o mais recente (posição -1)
    ultimo_arquivo = sia.get_files(group="PA", uf="PB", year=2026)[-1]
    
    # Obtém o mês atual do sistema
    mes_atual = datetime.now().month
    
    # Extrai o mês do nome do arquivo (últimos dois dígitos)
    mes_atual_arquivos = int(ultimo_arquivo.name[-1:])
    
    # Cria uma lista de meses de 1 a 12
    lista_meses = [n for n in range(1, 13)]
    
    # Define o mês esperado (considerando um atraso de 2 meses na disponibilização dos dados)
    mes_esperado = lista_meses[(mes_atual - 1) - 2]

    # Verifica se o mês do arquivo corresponde ao mês esperado
    if mes_esperado == mes_atual_arquivos:
        
        # Mensagem de sucesso indicando que o mês está correto
        print(f"Deu certo, mes atual é {mes_atual} mes do arquivo é {mes_atual_arquivos} e é igual o mês esperado que é {mes_esperado}")

        # Define o caminho onde o arquivo parquet será salvo
        output_path = 'data/sia_datasus.parquet'
        
        # Garante que o diretório existe (cria se não existir)
        output_dir = Path(output_path).parent
        output_dir.mkdir(parents=True, exist_ok=True)

        # Faz o download do arquivo
        arquivo_baixado = sia.download(ultimo_arquivo)
        
        # Converte o arquivo baixado para DataFrame
        df = arquivo_baixado.to_dataframe()

        # Salva o DataFrame em formato parquet
        df.to_parquet(output_path, index=False)

        # Retorna o caminho do arquivo salvo
        return output_path  

    else:
        # Mensagem indicando que o mês não corresponde ao esperado
        print(f"Deu errado, mes atual é {mes_atual} mes do arquivo é {mes_atual_arquivos} e é diferente o mês esperado que é {mes_esperado}")

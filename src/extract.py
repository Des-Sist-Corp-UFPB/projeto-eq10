import pandas as pd
from pysus.online_data.SIA import SIA
from datetime import datetime
from pathlib import Path





def extract_data(sia) -> Path:
    ultimo_arquivo = sia.get_files(group="PA", uf="PB", year=2026)[0]
    mes_atual = datetime.now().month
    mes_atual_arquivos = int(ultimo_arquivo.name[-2:])
    
    lista_meses = [n for n in range(1, 13)]
    mes_esperado = lista_meses[(mes_atual-1)-2]

    if mes_esperado == 2:
        print(f"Deu certo, mes atual é {mes_atual} mes do arquivo é {mes_atual_arquivos} e é igual o mês esperado que é {mes_esperado}")

        output_path = 'data/sia_datasus.parquet'
        output_dir = Path(output_path).parent
        output_dir.mkdir(parents=True, exist_ok=True)

        arquivo_baixado = sia.download(ultimo_arquivo)
        df = arquivo_baixado.to_dataframe()

        df.to_parquet(output_path, index=False)

        return output_path  

    else:
        print(f"Deu errado, mes atual é {mes_atual} mes do arquivo é {mes_atual_arquivos} e é diferente o mês esperado que é {mes_esperado}")


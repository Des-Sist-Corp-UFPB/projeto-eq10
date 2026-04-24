import pandas as pd
from pysus.online_data.SIA import SIA
from datetime import datetime
from pathlib import Path

import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)

logger = logging.getLogger(__name__)

def extract_data(sia) -> Path:
    try:
        logger.info("Iniciando extração de dados do DataSUS")

        # Busca arquivos disponíveis
        arquivos = sia.get_files(group="PA", uf="PB", year=2026)
        logger.info(f"Total de arquivos encontrados: {len(arquivos)}")

        # Último arquivo disponível
        ultimo_arquivo = arquivos[-1]
        logger.info(f"Último arquivo identificado: {ultimo_arquivo.name}")

        # Mês atual
        mes_atual = datetime.now().month

        # Mês do arquivo (ajuste aqui se necessário)
        mes_ultimo_arquivo = int(ultimo_arquivo.name[-1:])

        # Regra de atraso de 2 meses
        lista_meses = [n for n in range(1, 13)]
        mes_esperado = lista_meses[(mes_atual - 1) - 2]

        logger.info(
            f"Validação de mês | Atual: {mes_atual} | Arquivo: {mes_ultimo_arquivo} | Esperado: {mes_esperado}"
        )

        # 🔥 Regra de controle
        if mes_esperado == mes_ultimo_arquivo:

            logger.info("Mês válido — iniciando download")

            output_path = 'data/sia_datasus.parquet'
            output_dir = Path(output_path).parent
            output_dir.mkdir(parents=True, exist_ok=True)

            # Download
            arquivo_baixado = sia.download(ultimo_arquivo)
            logger.info("Download concluído")

            # Conversão
            df = arquivo_baixado.to_dataframe()
            logger.info(f"Arquivo convertido para DataFrame | Linhas: {len(df)}")

            # Salvando
            df.to_parquet(output_path, index=False)
            logger.info(f"Arquivo salvo em: {output_path}")

            return output_path  

        else:
            logger.warning(
                f"Mês inválido — extração não realizada | Atual: {mes_atual} | Arquivo: {mes_ultimo_arquivo} | Esperado: {mes_esperado}"
            )

    except Exception as e:
        logger.error(f"Erro na extração: {e}", exc_info=True)
        raise
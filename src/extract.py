from src.utils import get_target_period 
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
        
        # 1. Busca dinamicamente o ano e o mês esperado, já tratando virada de ano
        ano_alvo, mes_esperado = get_target_period(months_delay=2)

        # 2. Busca arquivos disponíveis usando o ano alvo calculado
        arquivos = sia.get_files(group="PA", uf="PB", year=ano_alvo)
        logger.info(f"Total de arquivos encontrados: {len(arquivos)}")

        # Trava de segurança extra caso o ano tenha virado e o SUS ainda não tenha criado a pasta
        if not arquivos:
            logger.warning(f"Nenhum arquivo encontrado no FTP do DataSUS para o ano {ano_alvo}.")
            return None

        logger.info(f"Total de arquivos encontrados: {len(arquivos)}")

        # Último arquivo disponível
        ultimo_arquivo = arquivos[-1]
        logger.info(f"Último arquivo identificado: {ultimo_arquivo.name}")

        # 3. Correção do Bug de Data: Extrai os 2 últimos caracteres ANTES da extensão
        # Ex: "PAPB2612.dbc" -> pega "12" ao invés de apenas "2"
        str_mes = Path(ultimo_arquivo.name).stem[-2:]
        try:
            mes_ultimo_arquivo = int(str_mes)
        except ValueError:
            logger.error(f"Erro ao extrair o mês do arquivo {ultimo_arquivo.name}. Finalizando extração.")
            return None

        logger.info(
            f"Validação de mês | Arquivo FTP: {mes_ultimo_arquivo:02d} | Esperado: {mes_esperado:02d} | Ano Alvo: {ano_alvo}"
        )


        # 4. Regra de controle
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
                f"Mês inválido — extração não realizada | Arquivo FTP: {mes_ultimo_arquivo:02d} | Esperado: {mes_esperado:02d}"
            )
            # Retorna None para que o orquestrador (main.py) saiba que deve parar
            return None

    except Exception as e:
        logger.error(f"Erro na extração: {e}", exc_info=True)
        raise
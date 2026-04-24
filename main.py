import sys
from pysus.online_data.SIA import SIA
import pandas as pd
from datetime import datetime
from src.extract import extract_data
from src.transform import transform_datasus
from pathlib import Path
from src.load import check_data_exists, load_data_sus
from src.utils import get_target_period

import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s"
)

logger = logging.getLogger(__name__)

sia = SIA().load()

BASE_DIR = Path(__file__).resolve().parent
file_path = BASE_DIR / "data" / "sia_datasus.parquet"
file_path_to_save = BASE_DIR / "data" / "sia_datasus_transformed.parquet"

if __name__ == "__main__":
    try:
        logger.info("🚀 Iniciando pipeline ETL")
        
        # DEFINIÇÃO DO PERÍODO
        # Toda a lógica complexa de datas agora fica escondida e segura dentro de utils.py
        ano_alvo, mes_esperado = get_target_period(months_delay=2)

        # FAIL FAST
        if check_data_exists('data_sus', ano_alvo, mes_esperado):
            logger.warning(f"🛑 Dados do período {mes_esperado:02d}/{ano_alvo} já constam no banco.")
            logger.info("🎉 ETL encerrada precocemente para evitar duplicidade.")
            sys.exit(0) 

        # EXTRACT
        logger.info("🔄 Etapa: EXTRACT")
        extract_data(sia)
        logger.info("✅ Extração concluída")

        # TRANSFORM
        logger.info("🔄 Etapa: TRANSFORM")
        df = transform_datasus(file_path)
        logger.info(f"✅ Transformação concluída | Linhas: {len(df)}")

        # SAVE INTERMEDIÁRIO
        df.to_parquet(file_path_to_save, index=False)
        logger.info(f"💾 Dados transformados salvos em: {file_path_to_save}")

        # (opcional) leitura novamente
        df = pd.read_parquet(file_path_to_save, engine="pyarrow")
        logger.info("📥 Releitura do arquivo transformado concluída")

        # LOAD
        logger.info("🔄 Etapa: LOAD")
        load_data_sus('data_sus', df)
        logger.info("✅ Carga finalizada com sucesso")

        logger.info("🎉 Pipeline ETL finalizado com sucesso!")

    except Exception as e:
        logger.error(f"❌ Erro no pipeline: {e}", exc_info=True)
        raise

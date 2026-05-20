"""Entrada publica da camada isolada de IA para SIA/DATASUS."""

from src.ai.data_provider import load_controlled_datasus_dataframe
from src.ai.month_checker import validar_mes_solicitado_no_prompt
from src.ai.pandasai_runner import executar_pergunta_com_pandasai
from src.ai.prompt_guard import validar_prompt
from src.ai.query_logger import log_ai_question

GENERIC_AI_ERROR_MESSAGE = (
    "Não foi possível processar a pergunta. Verifique a configuração da camada de IA."
)


def perguntar_datasus(prompt_usuario: str) -> str:
    """Recebe uma pergunta sobre dados SIA/DATASUS sem acionar a ETL principal."""
    valido, mensagem = validar_prompt(prompt_usuario)

    if not valido:
        log_ai_question(prompt_usuario, status="bloqueado_prompt", detail=mensagem)
        return mensagem

    mes_valido, mensagem_mes = validar_mes_solicitado_no_prompt(prompt_usuario)

    if not mes_valido:
        log_ai_question(
            prompt_usuario,
            status="bloqueado_mes_indisponivel",
            detail=mensagem_mes,
        )
        return mensagem_mes

    try:
        df, data_inicio, data_fim_exclusiva = load_controlled_datasus_dataframe()

        if df.empty:
            mensagem_sem_dados = (
                "Ainda não há dados disponíveis no sistema para análise estatística."
            )
            log_ai_question(prompt_usuario, status="sem_dados", detail=mensagem_sem_dados)
            return mensagem_sem_dados

        resposta = executar_pergunta_com_pandasai(
            df,
            prompt_usuario,
            data_inicio,
            data_fim_exclusiva,
        )
    except RuntimeError as exc:
        mensagem_erro = str(exc)
        log_ai_question(prompt_usuario, status="erro_configuracao", detail=mensagem_erro)
        return mensagem_erro
    except Exception:
        log_ai_question(prompt_usuario, status="erro_inesperado")
        return GENERIC_AI_ERROR_MESSAGE

    log_ai_question(prompt_usuario, status="respondido")
    return resposta

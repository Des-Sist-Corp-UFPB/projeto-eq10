from datetime import datetime

def get_target_period(months_delay: int = 2) -> tuple[int, int]:
    #Calcula o mês e o ano alvo baseado em um atraso (delay) de meses.
    #Trata automaticamente a virada de ano.
    
    hoje = datetime.now()
    mes_esperado = hoje.month - months_delay
    ano_alvo = hoje.year
    
    # Se o mês calculado for menor ou igual a zero, significa que recuamos para o ano anterior
    if mes_esperado <= 0:
        mes_esperado += 12 # Corrige o mês (ex: 0 vira 12, -1 vira 11)
        ano_alvo -= 1      # Subtrai 1 do ano atual
        
    return ano_alvo, mes_esperado
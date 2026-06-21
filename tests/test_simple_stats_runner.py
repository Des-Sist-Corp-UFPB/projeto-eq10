import inspect
import unittest
from datetime import date

import pandas as pd

from src.ai.simple_stats_runner import (
    SIMPLE_STATS_UNAVAILABLE_MESSAGE,
    executar_pergunta_estatistica_simples,
    executar_pergunta_simples,
)


class TestSimpleStatsRunner(unittest.TestCase):
    def setUp(self):
        self.df = pd.DataFrame(
            [
                {
                    "data": date(2026, 1, 10),
                    "municipio_atendimento": "Cajazeiras",
                    "municipio_residencia": "Sousa",
                    "valor_aprovado": 10.5,
                    "valor_apresentado": 11.5,
                    "frequencia": 2,
                    "sexo": "M",
                    "unidade": "Hospital Regional",
                    "procedimento": "Consulta medica",
                    "raca_cor": "Parda",
                    "ocupacao": "Agricultor",
                    "quantidade_apresentada": 5,
                    "idade": 30,
                },
                {
                    "data": date(2026, 2, 20),
                    "municipio_atendimento": "Cajazeiras",
                    "municipio_residencia": "Cajazeiras",
                    "valor_aprovado": 20,
                    "valor_apresentado": 21,
                    "frequencia": 3,
                    "sexo": "F",
                    "unidade": "UPA Central",
                    "procedimento": "Exame laboratorial",
                    "raca_cor": "Branca",
                    "ocupacao": "Professor",
                    "quantidade_apresentada": 8,
                    "idade": 40,
                },
                {
                    "data": date(2026, 3, 15),
                    "municipio_atendimento": "Sousa",
                    "municipio_residencia": "Sousa",
                    "valor_aprovado": 7,
                    "valor_apresentado": 8,
                    "frequencia": 4,
                    "sexo": "F",
                    "unidade": "Hospital Regional",
                    "procedimento": "Consulta medica",
                    "raca_cor": "Parda",
                    "ocupacao": "Agricultor",
                    "quantidade_apresentada": 6,
                    "idade": 20,
                },
            ]
        )
        self.data_inicio = date(2026, 1, 1)
        self.data_fim = date(2026, 4, 1)

    def _ask(self, prompt):
        return executar_pergunta_estatistica_simples(
            self.df,
            prompt,
            self.data_inicio,
            self.data_fim,
        )

    def test_total_valor_aprovado_por_municipio(self):
        resposta = self._ask("total de valor aprovado por município")

        self.assertIn("Total de valor aprovado por município de atendimento", resposta)
        self.assertIn("Cajazeiras: R$ 30,50", resposta)
        self.assertIn("Sousa: R$ 7,00", resposta)

    def test_sugestao_valor_aprovado_por_municipio_de_atendimento(self):
        resposta = self._ask("Valor aprovado por município de atendimento")

        self.assertIn("Total de valor aprovado por município de atendimento", resposta)
        self.assertIn("Cajazeiras: R$ 30,50", resposta)
        self.assertIn("Sousa: R$ 7,00", resposta)

    def test_total_valor_aprovado_por_municipio_de_residencia(self):
        resposta = self._ask("total de valor aprovado por município de residência")

        self.assertIn("Total de valor aprovado por município de residência", resposta)
        self.assertIn("Cajazeiras: R$ 20,00", resposta)
        self.assertIn("Sousa: R$ 17,50", resposta)

    def test_alias_publico_executar_pergunta_simples(self):
        resposta = executar_pergunta_simples(
            self.df,
            "total geral de valor aprovado",
            self.data_inicio,
            self.data_fim,
        )

        self.assertIn("Total geral de valor aprovado: R$ 37,50", resposta)

    def test_frequencia_total_por_sexo(self):
        resposta = self._ask("frequência total por sexo")

        self.assertIn("Frequência total por sexo", resposta)
        self.assertIn("F: 7", resposta)
        self.assertIn("M: 2", resposta)

    def test_unidades_com_maior_quantidade_apresentada(self):
        resposta = self._ask("unidades com maior quantidade apresentada")

        self.assertIn("Unidades com maior quantidade apresentada", resposta)
        self.assertIn("1. Hospital Regional: 11", resposta)
        self.assertIn("2. UPA Central: 8", resposta)

    def test_sugestao_procedimentos_com_maior_valor_aprovado(self):
        resposta = self._ask("Procedimentos com maior valor aprovado")

        self.assertIn("Ranking por procedimento usando valor aprovado", resposta)
        self.assertIn("1. Exame laboratorial: R$ 20,00", resposta)
        self.assertIn("2. Consulta medica: R$ 17,50", resposta)

    def test_sugestao_valor_aprovado_por_raca_cor(self):
        resposta = self._ask("Valor aprovado por raça/cor")

        self.assertIn("Ranking por raça/cor usando valor aprovado", resposta)
        self.assertIn("1. Branca: R$ 20,00", resposta)
        self.assertIn("2. Parda: R$ 17,50", resposta)

    def test_media_de_idade(self):
        resposta = self._ask("média de idade dos atendimentos")

        self.assertIn("Média de idade dos atendimentos: 30,00 anos", resposta)

    def test_normaliza_acentos_em_perguntas_simples(self):
        resposta = self._ask("media de idade dos atendimentos no ultimo mes")

        self.assertIn("Média de idade dos atendimentos: 30,00 anos", resposta)

    def test_total_geral_valor_aprovado(self):
        resposta = self._ask("total geral de valor aprovado")

        self.assertIn("Total geral de valor aprovado: R$ 37,50", resposta)

    def test_total_geral_valor_apresentado(self):
        resposta = self._ask("total geral de valor apresentado")

        self.assertIn("Total geral de valor apresentado: R$ 40,50", resposta)

    def test_total_geral_quantidade_apresentada(self):
        resposta = self._ask("total de quantidade apresentada")

        self.assertIn("Total geral de quantidade apresentada: 19", resposta)

    def test_total_geral_frequencia(self):
        resposta = self._ask("soma total de frequencia")

        self.assertIn("Total geral de frequencia: 9", resposta)

    def test_contagem_de_procedimentos_distintos(self):
        resposta = self._ask("contagem de procedimentos")

        self.assertIn("Contagem de procedimentos distintos: 2", resposta)

    def test_ultima_data_disponivel(self):
        resposta = self._ask("qual a data mais recente disponivel")

        self.assertIn("Data mais recente disponivel: 15/03/2026", resposta)
        self.assertIn("Mes mais recente disponivel: 03/2026", resposta)

    def test_contagem_de_registros(self):
        resposta = self._ask("contagem de registros")

        self.assertIn("Contagem de registros: 3", resposta)

    def test_ranking_basico_por_municipio(self):
        resposta = self._ask("ranking por município")

        self.assertIn("Ranking por município de atendimento usando valor aprovado", resposta)
        self.assertIn("1. Cajazeiras: R$ 30,50", resposta)
        self.assertIn("2. Sousa: R$ 7,00", resposta)

    def test_ranking_basico_por_procedimento(self):
        resposta = self._ask("ranking por procedimento por valor aprovado")

        self.assertIn("Ranking por procedimento usando valor aprovado", resposta)
        self.assertIn("1. Exame laboratorial: R$ 20,00", resposta)
        self.assertIn("2. Consulta medica: R$ 17,50", resposta)

    def test_ranking_basico_por_sexo_com_frequencia(self):
        resposta = self._ask("ranking por sexo por frequência")

        self.assertIn("Ranking por sexo usando frequência", resposta)
        self.assertIn("1. F: 7", resposta)
        self.assertIn("2. M: 2", resposta)

    def test_pergunta_nao_reconhecida(self):
        resposta = self._ask("qual procedimento cresceu mais?")

        self.assertEqual(resposta, SIMPLE_STATS_UNAVAILABLE_MESSAGE)

    def test_runner_nao_contem_escrita_em_banco_ou_arquivos(self):
        import src.ai.simple_stats_runner as simple_stats_runner

        source = inspect.getsource(simple_stats_runner)
        upper_source = source.upper()

        for fragment in [".to_sql", "to_sql(", "to_parquet", "to_csv", "open("]:
            self.assertNotIn(fragment, source)

        for command in ["INSERT", "UPDATE", "DELETE", "DROP", "ALTER", "CREATE", "TRUNCATE"]:
            self.assertNotRegex(upper_source, rf"\b{command}\b")


if __name__ == "__main__":
    unittest.main()

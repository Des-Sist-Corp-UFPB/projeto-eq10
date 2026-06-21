import unittest

from src.auth.validation import validate_login_fields, validate_register_fields


class TestAuthValidation(unittest.TestCase):
    def test_login_exige_email(self):
        errors = validate_login_fields("", "senha-forte")

        self.assertEqual(errors["email"], "Informe seu e-mail.")

    def test_login_exige_email_valido(self):
        errors = validate_login_fields("email-invalido", "senha-forte")

        self.assertEqual(errors["email"], "Informe um e-mail válido.")

    def test_login_exige_senha(self):
        errors = validate_login_fields("ana@example.com", "")

        self.assertEqual(errors["senha"], "Informe sua senha.")

    def test_cadastro_exige_nome(self):
        errors = validate_register_fields("", "ana@example.com", "senha-forte", "senha-forte")

        self.assertEqual(errors["nome"], "Informe seu nome.")

    def test_cadastro_exige_email(self):
        errors = validate_register_fields("Ana", "", "senha-forte", "senha-forte")

        self.assertEqual(errors["email"], "Informe seu e-mail.")

    def test_cadastro_exige_email_valido(self):
        errors = validate_register_fields("Ana", "ana", "senha-forte", "senha-forte")

        self.assertEqual(errors["email"], "Informe um e-mail válido.")

    def test_cadastro_exige_senha(self):
        errors = validate_register_fields("Ana", "ana@example.com", "", "")

        self.assertEqual(errors["senha"], "Informe uma senha.")

    def test_cadastro_exige_senha_minima(self):
        errors = validate_register_fields("Ana", "ana@example.com", "curta", "curta")

        self.assertEqual(errors["senha"], "A senha deve ter pelo menos 8 caracteres.")

    def test_cadastro_exige_confirmacao(self):
        errors = validate_register_fields("Ana", "ana@example.com", "senha-forte", "")

        self.assertEqual(errors["confirmar_senha"], "Confirme sua senha.")

    def test_cadastro_exige_senhas_iguais(self):
        errors = validate_register_fields("Ana", "ana@example.com", "senha-forte", "outra-senha")

        self.assertEqual(errors["confirmar_senha"], "As senhas não coincidem.")


if __name__ == "__main__":
    unittest.main()

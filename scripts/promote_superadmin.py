#!/usr/bin/env python3
"""Script de promocao de Super Admin.

Localiza o usuario 'sg123c20@gmail.com' (Gabriel Nunes) na base de dados
de autenticacao e atualiza seu papel para 'super_admin'.

Pode ser executado multiplas vezes sem efeitos colaterais (idempotente).

Uso:
    python scripts/promote_superadmin.py
"""

from __future__ import annotations

import sys
from pathlib import Path

# Adiciona a raiz do projeto ao path para que os imports funcionem
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")
load_dotenv(ROOT / "config" / ".env")

from sqlalchemy import text

from src.auth.user_service import get_auth_engine
from src.auth.roles import ROLE_SUPER_ADMIN
from src.audit.audit_log_service import AuditLogService, EVENT_ROLE_CHANGED

TARGET_EMAIL = "sg123c20@gmail.com"
TARGET_NAME = "Gabriel Nunes"


def main() -> None:
    print(f"[promote_superadmin] Conectando ao banco de autenticacao...")
    engine = get_auth_engine()

    # Roda migracoes de schema (cria can_view_audit se nao existir, etc.)
    print(f"[promote_superadmin] Garantindo schema atualizado...")
    from src.auth.user_service import UserService
    UserService(engine, initialize_schema=True)

    # Garante que a tabela audit_log existe
    AuditLogService(engine, initialize_schema=True)

    with engine.begin() as conn:
        row = conn.execute(
            text("SELECT id, nome, email, role FROM usuarios WHERE lower(email) = :email LIMIT 1"),
            {"email": TARGET_EMAIL.lower()},
        ).mappings().first()

        if row is None:
            print(f"[ERRO] Usuario '{TARGET_EMAIL}' nao encontrado no banco.")
            print("  Verifique se a conta foi criada antes de executar este script.")
            sys.exit(1)

        current_role = row["role"]
        user_id = int(row["id"])
        user_nome = row["nome"]

        if current_role == ROLE_SUPER_ADMIN:
            print(f"[OK] '{user_nome}' ({TARGET_EMAIL}) ja e Super Admin. Nenhuma alteracao necessaria.")
            return

        conn.execute(
            text("""
                UPDATE usuarios
                SET role = :role,
                    can_view_audit = true,
                    atualizado_em = NOW()
                WHERE id = :id
            """),
            {"role": ROLE_SUPER_ADMIN, "id": user_id},
        )

    # Registra o evento de auditoria
    audit = AuditLogService(engine, initialize_schema=False)
    audit.log_event(
        EVENT_ROLE_CHANGED,
        user_id=user_id,
        user_email=TARGET_EMAIL,
        detalhe=f"promocao_script | role_anterior={current_role} | novo_role={ROLE_SUPER_ADMIN}",
    )

    print(f"[OK] '{user_nome}' ({TARGET_EMAIL}) promovido a Super Admin com sucesso!")
    print(f"     ID do usuario: {user_id}")
    print(f"     Evento registrado no audit_log.")


if __name__ == "__main__":
    main()

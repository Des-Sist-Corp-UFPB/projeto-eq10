"""Pagina de administracao restrita: log de auditoria e gestao de usuarios.

Visivel apenas para Super Admins e usuarios com can_view_audit=True.
"""

from __future__ import annotations

import html
from typing import Any

import streamlit as st

from src.auth.roles import (
    ROLE_SUPER_ADMIN,
    ROLE_USER,
    VALID_ROLES,
    can_view_audit_log,
    is_super_admin,
    role_display_name,
)
from src.auth.session import get_authenticated_user

ADMIN_PAGE_CSS = """
<style>
/* ── Audit Log Table ──────────────────────────── */
.audit-table-wrap {
    overflow-x: auto;
    border-radius: 0.85rem;
    border: 1px solid #E2E8F0;
    margin-top: 0.5rem;
}
.audit-table {
    width: 100%;
    border-collapse: collapse;
    font-size: 0.82rem;
    background: #FFFFFF;
}
.audit-table thead tr {
    background: #F1F5F9;
    color: #475569;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.04em;
    font-size: 0.72rem;
}
.audit-table th, .audit-table td {
    padding: 0.55rem 0.75rem;
    text-align: left;
    border-bottom: 1px solid #F1F5F9;
    white-space: nowrap;
    max-width: 260px;
    overflow: hidden;
    text-overflow: ellipsis;
}
.audit-table tbody tr:hover {
    background: #F8FAFC;
}
/* Linha de alerta: prompt_guard_block */
.audit-table tr.audit-row-alert {
    background: #FEF2F2 !important;
    color: #991B1B !important;
}
.audit-table tr.audit-row-alert td {
    color: #991B1B !important;
    font-weight: 700;
}
.audit-table tr.audit-row-alert:hover {
    background: #FEE2E2 !important;
}
/* Badge de evento */
.audit-badge {
    display: inline-block;
    padding: 0.18rem 0.52rem;
    border-radius: 9999px;
    font-size: 0.72rem;
    font-weight: 700;
    white-space: nowrap;
}
.badge-login         { background:#DBEAFE; color:#1D4ED8; }
.badge-account_created { background:#D1FAE5; color:#065F46; }
.badge-account_deleted { background:#FEE2E2; color:#991B1B; }
.badge-chat_prompt   { background:#EDE9FE; color:#6D28D9; }
.badge-prompt_guard_block { background:#FEE2E2; color:#991B1B; }
.badge-access_granted { background:#D1FAE5; color:#065F46; }
.badge-access_revoked { background:#FEF3C7; color:#92400E; }
.badge-role_changed  { background:#FEF3C7; color:#92400E; }
.badge-default       { background:#F1F5F9; color:#475569; }

/* ── Admin Section Header ─────────────────────── */
.admin-section-title {
    font-size: 1.05rem;
    font-weight: 800;
    color: #1E293B;
    margin: 1.5rem 0 0.65rem;
    padding-bottom: 0.35rem;
    border-bottom: 2px solid #E2E8F0;
}
/* ── User Table ───────────────────────────────── */
.user-table {
    width: 100%;
    border-collapse: collapse;
    font-size: 0.83rem;
    background: #FFFFFF;
    border-radius: 0.85rem;
    overflow: hidden;
    border: 1px solid #E2E8F0;
}
.user-table thead tr {
    background: #F1F5F9;
    color: #475569;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.04em;
    font-size: 0.72rem;
}
.user-table th, .user-table td {
    padding: 0.55rem 0.75rem;
    border-bottom: 1px solid #F1F5F9;
}
.user-table tbody tr:hover { background: #F8FAFC; }
</style>
"""


def _escape(v: Any) -> str:
    return html.escape(str(v or ""), quote=False)


def _badge_class(evento: str) -> str:
    known = {
        "login", "account_created", "account_deleted", "chat_prompt",
        "prompt_guard_block", "access_granted", "access_revoked", "role_changed",
    }
    return f"badge-{evento}" if evento in known else "badge-default"


def _event_display(evento: str) -> str:
    labels = {
        "login": "Login",
        "account_created": "Conta criada",
        "account_deleted": "Conta excluída",
        "chat_prompt": "Pergunta IA",
        "prompt_guard_block": "⚠ Prompt bloqueado",
        "access_granted": "Acesso concedido",
        "access_revoked": "Acesso revogado",
        "role_changed": "Papel alterado",
    }
    return labels.get(evento, evento)


def _format_dt(dt: Any) -> str:
    if dt is None:
        return "—"
    try:
        return dt.strftime("%d/%m/%Y %H:%M:%S")
    except Exception:
        return str(dt)


@st.cache_resource(show_spinner=False)
def _get_user_service():
    from src.auth.user_service import UserService
    return UserService.from_environment()


@st.cache_resource(show_spinner=False)
def _get_audit_service():
    from src.audit.audit_log_service import AuditLogService
    return AuditLogService.from_environment()


def _render_audit_table(entries: list) -> None:
    """Renderiza a tabela do log de auditoria com destaque vermelho para bloqueios."""
    if not entries:
        st.info("Nenhum evento registrado ainda.")
        return

    rows_html = ""
    for entry in entries:
        is_alert = entry.evento == "prompt_guard_block"
        row_class = " class=\"audit-row-alert\"" if is_alert else ""
        badge_cls = _badge_class(entry.evento)
        evento_label = _event_display(entry.evento)
        prompt_cell = (
            f"<td title=\"{_escape(entry.prompt_text)}\">{_escape((entry.prompt_text or '')[:60])}{'…' if entry.prompt_text and len(entry.prompt_text) > 60 else ''}</td>"
            if entry.prompt_text
            else "<td>—</td>"
        )
        rows_html += f"""
        <tr{row_class}>
            <td>{_escape(_format_dt(entry.criado_em))}</td>
            <td><span class="audit-badge {badge_cls}">{_escape(evento_label)}</span></td>
            <td>{_escape(entry.user_email or '—')}</td>
            {prompt_cell}
            <td title="{_escape(entry.detalhe or '')}">{_escape((entry.detalhe or '')[:60])}</td>
        </tr>"""

    st.markdown(
        f"""
        <div class="audit-table-wrap">
        <table class="audit-table">
            <thead>
                <tr>
                    <th>Data/Hora</th>
                    <th>Evento</th>
                    <th>E-mail</th>
                    <th>Prompt</th>
                    <th>Detalhe</th>
                </tr>
            </thead>
            <tbody>{rows_html}</tbody>
        </table>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _render_user_management(user: dict, service) -> None:
    """Renderiza a secao de gestao de usuarios (apenas Super Admin)."""
    st.markdown('<p class="admin-section-title">👥 Gestão de Usuários</p>', unsafe_allow_html=True)

    try:
        all_users = service.get_all_users()
    except Exception as exc:
        st.error(f"Erro ao carregar usuários: {exc}")
        return

    if not all_users:
        st.info("Nenhum usuário encontrado.")
        return

    admin_id = int(user["id"])
    admin_email = user.get("email", "")

    for u in all_users:
        if u.id == admin_id:
            # Nao mostrar opcoes de remover/alterar a si mesmo
            with st.expander(f"**{u.nome}** · {u.email} · *{role_display_name(u.role)}* (você)"):
                st.caption("Este é seu próprio perfil. Não é possível alterar seu papel aqui.")
            continue

        with st.expander(f"**{u.nome}** · {u.email} · *{role_display_name(u.role)}*"):
            col1, col2, col3 = st.columns([2, 2, 2])

            with col1:
                new_role = st.selectbox(
                    "Papel",
                    options=list(VALID_ROLES),
                    index=0 if u.role == ROLE_USER else 1,
                    format_func=role_display_name,
                    key=f"role_select_{u.id}",
                )
                if st.button("Salvar papel", key=f"save_role_{u.id}", use_container_width=True):
                    if new_role != u.role:
                        try:
                            service.set_role(u.id, new_role, acting_admin_id=admin_id, acting_admin_email=admin_email)
                            st.success(f"Papel de {u.nome} alterado para {role_display_name(new_role)}.")
                            st.cache_resource.clear()
                            st.rerun()
                        except Exception as exc:
                            st.error(f"Erro: {exc}")
                    else:
                        st.info("Nenhuma alteração.")

            with col2:
                audit_label = "✅ Tem acesso ao log" if u.can_view_audit else "❌ Sem acesso ao log"
                st.caption(f"Log de auditoria: {audit_label}")
                if u.can_view_audit:
                    if st.button("Revogar acesso ao log", key=f"revoke_audit_{u.id}", use_container_width=True):
                        try:
                            service.set_audit_access(u.id, False, acting_admin_id=admin_id, acting_admin_email=admin_email)
                            st.success(f"Acesso ao log revogado para {u.nome}.")
                            st.rerun()
                        except Exception as exc:
                            st.error(f"Erro: {exc}")
                else:
                    if st.button("Conceder acesso ao log", key=f"grant_audit_{u.id}", use_container_width=True):
                        try:
                            service.set_audit_access(u.id, True, acting_admin_id=admin_id, acting_admin_email=admin_email)
                            st.success(f"Acesso ao log concedido para {u.nome}.")
                            st.rerun()
                        except Exception as exc:
                            st.error(f"Erro: {exc}")

            with col3:
                st.caption("Zona de perigo")
                confirm_key = f"confirm_delete_{u.id}"
                if not st.session_state.get(confirm_key):
                    if st.button(f"🗑 Excluir conta", key=f"delete_user_{u.id}", use_container_width=True):
                        st.session_state[confirm_key] = True
                        st.rerun()
                else:
                    st.warning(f"Confirmar exclusão de **{u.nome}**?")
                    c1, c2 = st.columns(2)
                    with c1:
                        if st.button("✅ Confirmar", key=f"confirm_yes_{u.id}", use_container_width=True):
                            try:
                                service.soft_delete_user(u.id)
                                st.success(f"Conta de {u.nome} excluída.")
                                st.session_state.pop(confirm_key, None)
                                st.rerun()
                            except Exception as exc:
                                st.error(f"Erro: {exc}")
                    with c2:
                        if st.button("❌ Cancelar", key=f"confirm_no_{u.id}", use_container_width=True):
                            st.session_state.pop(confirm_key, None)
                            st.rerun()


def render_admin_page() -> None:
    """Renderiza a pagina de administracao restrita (Uso Restrito)."""
    st.markdown(ADMIN_PAGE_CSS, unsafe_allow_html=True)

    user = get_authenticated_user(st.session_state)

    # ── Guarda de acesso ────────────────────────────────────────────
    if not user or not can_view_audit_log(user):
        st.error("🔒 Acesso restrito. Esta área é exclusiva para administradores autorizados.")
        st.stop()
        return

    # ── Cabecalho ───────────────────────────────────────────────────
    st.markdown("## 🔐 Uso Restrito — Painel de Auditoria")
    st.caption(
        f"Você está logado como **{_escape(user.get('nome', ''))}** "
        f"· papel: *{role_display_name(user.get('role', 'user'))}*"
    )
    st.divider()

    # ── Gestao de usuarios (apenas Super Admin) ─────────────────────
    if is_super_admin(user):
        try:
            svc = _get_user_service()
            _render_user_management(user, svc)
        except Exception as exc:
            st.error(f"Erro ao carregar gestão de usuários: {exc}")
        st.divider()

    # ── Log de auditoria ─────────────────────────────────────────────
    st.markdown('<p class="admin-section-title">📋 Log de Auditoria</p>', unsafe_allow_html=True)

    col_limit, col_refresh = st.columns([3, 1])
    with col_limit:
        limit = st.slider("Número de eventos a exibir", min_value=10, max_value=500, value=100, step=10)
    with col_refresh:
        st.write("")
        st.write("")
        if st.button("🔄 Atualizar", use_container_width=True, key="audit-refresh"):
            st.rerun()

    try:
        audit_svc = _get_audit_service()
        entries = audit_svc.get_recent_logs(limit=limit)
        _render_audit_table(entries)
    except Exception as exc:
        st.error(f"Erro ao carregar log de auditoria: {exc}")

    st.caption(f"Exibindo até {limit} eventos mais recentes. Linhas em vermelho indicam prompts bloqueados pelo Prompt Guard.")

"""Shared visual styling helpers for the Streamlit UI."""

from __future__ import annotations

import os
from typing import Any
from urllib.parse import urlparse

LOGO_URL_ENV_VARS = (
    "APP_LOGO_URL",
    "APP_LOGO_PUBLIC_URL",
    "APP_BRAND_LOGO_URL",
    "SIDEBAR_LOGO_URL",
    "PUBLIC_LOGO_URL",
    "MINIO_LOGO_URL",
    "MINIO_PUBLIC_LOGO_URL",
    "MINIO_APP_LOGO_URL",
    "LOGO_URL",
)
AUDIT_PAGE_SCOPE = ".st-key-audit-page-shell"

GLOBAL_LIGHT_THEME_CSS = """
<style>
:root,
html,
body,
.stApp {
    color-scheme: light;
}

.stApp,
[data-testid="stAppViewContainer"],
[data-testid="stMain"],
[data-testid="stMainBlockContainer"] {
    background: #F5F7FB !important;
    color: #111827 !important;
}

/* Widget-level overrides such as [data-testid="stSelectbox"] div[data-baseweb="select"] > div
   and [data-testid="stDataFrame"]
   are intentionally scoped to page-specific CSS below. */
</style>
"""

AUDIT_PAGE_CSS = """
<style>
/* Audit page polish for native Streamlit controls. Dynamic data is rendered by Streamlit widgets. */
.st-key-audit-page-shell [data-testid="stMetric"] {
    background: #FFFFFF !important;
    border: 1px solid #E2E8F0;
    border-radius: 0.75rem;
    padding: 0.72rem 0.85rem;
    box-shadow: 0 8px 18px rgba(15, 23, 42, 0.045);
}
.st-key-audit-page-shell [data-testid="stMetric"] label,
.st-key-audit-page-shell [data-testid="stMetric"] div,
.st-key-audit-page-shell [data-testid="stMetric"] p {
    color: #111827 !important;
}

.st-key-audit-page-shell [data-testid="stExpander"] details {
    background: #FFFFFF !important;
    border-color: #E2E8F0 !important;
    border-radius: 0.75rem !important;
    box-shadow: 0 8px 18px rgba(15, 23, 42, 0.04);
}
.st-key-audit-page-shell [data-testid="stExpander"] summary,
.st-key-audit-page-shell [data-testid="stExpander"] summary p,
.st-key-audit-page-shell [data-testid="stExpander"] label,
.st-key-audit-page-shell [data-testid="stExpander"] span,
.st-key-audit-page-shell [data-testid="stExpander"] p {
    color: #111827 !important;
}

.st-key-audit-page-shell [data-testid="stSelectbox"] div[data-baseweb="select"] > div,
.st-key-audit-page-shell [data-testid="stTextInput"] input,
.st-key-audit-page-shell [data-testid="stDateInput"] input {
    background: #FFFFFF !important;
    border-color: #CBD5E1 !important;
    color: #111827 !important;
    box-shadow: none !important;
}
.st-key-audit-page-shell [data-testid="stSelectbox"] div[data-baseweb="select"] span,
.st-key-audit-page-shell [data-testid="stTextInput"] input::placeholder,
.st-key-audit-page-shell [data-testid="stDateInput"] input::placeholder {
    color: #64748B !important;
}
.st-key-audit-page-shell [data-testid="stSelectbox"] label,
.st-key-audit-page-shell [data-testid="stTextInput"] label,
.st-key-audit-page-shell [data-testid="stDateInput"] label {
    color: #111827 !important;
}
.st-key-audit-page-shell [data-testid="stSelectbox"] svg,
.st-key-audit-page-shell [data-testid="stDateInput"] svg {
    color: #64748B !important;
    fill: #64748B !important;
}

.st-key-audit-page-shell [data-testid="stDataFrame"] {
    background: #FFFFFF !important;
    border: 1px solid #E2E8F0 !important;
    border-radius: 0.75rem !important;
    box-shadow: 0 8px 18px rgba(15, 23, 42, 0.04);
    color: #111827 !important;
}
.st-key-audit-page-shell [data-testid="stDataFrame"] div,
.st-key-audit-page-shell [data-testid="stDataFrame"] span,
.st-key-audit-page-shell [data-testid="stDataFrame"] canvas {
    color: #111827 !important;
}
.st-key-audit-page-shell [data-testid="stDataFrame"] [role="grid"],
.st-key-audit-page-shell [data-testid="stDataFrame"] [role="row"],
.st-key-audit-page-shell [data-testid="stDataFrame"] [role="columnheader"],
.st-key-audit-page-shell [data-testid="stDataFrame"] [role="gridcell"] {
    background: #FFFFFF !important;
    color: #111827 !important;
}

.st-key-audit-refresh [data-testid="stButton"] button,
.st-key-audit-clear-filters [data-testid="stButton"] button,
.st-key-audit-empty-clear-filters [data-testid="stButton"] button,
.st-key-audit-open-selected-detail [data-testid="stButton"] button,
.st-key-audit-detail-close [data-testid="stButton"] button {
    background: #FFFFFF !important;
    color: #111827 !important;
    border: 1px solid #CBD5E1 !important;
    border-radius: 0.7rem !important;
    box-shadow: 0 6px 14px rgba(15, 23, 42, 0.045) !important;
}
.st-key-audit-refresh [data-testid="stButton"] button:hover,
.st-key-audit-clear-filters [data-testid="stButton"] button:hover,
.st-key-audit-empty-clear-filters [data-testid="stButton"] button:hover,
.st-key-audit-open-selected-detail [data-testid="stButton"] button:hover,
.st-key-audit-detail-close [data-testid="stButton"] button:hover {
    border-color: #7B2CBF !important;
    color: #4C1D95 !important;
}
.st-key-audit-apply-filters [data-testid="stButton"] button {
    background: linear-gradient(135deg, #7B2CBF 0%, #2563EB 100%) !important;
    color: #FFFFFF !important;
    border: 0 !important;
    border-radius: 0.7rem !important;
    box-shadow: 0 8px 18px rgba(76, 29, 149, 0.18) !important;
}
.st-key-audit-apply-filters [data-testid="stButton"] button * {
    color: #FFFFFF !important;
}

[data-testid="stDialog"] {
    background: #FFFFFF !important;
    color: #111827 !important;
}
</style>
"""


def apply_global_light_styles(st_module: Any) -> None:
    """Apply deployment-safe light styling to native Streamlit widgets."""
    st_module.markdown(GLOBAL_LIGHT_THEME_CSS, unsafe_allow_html=True)


def apply_audit_light_styles(st_module: Any) -> None:
    """Apply compact light styling for the audit page."""
    st_module.markdown(AUDIT_PAGE_CSS, unsafe_allow_html=True)


def get_configured_logo_url(environ: dict[str, str] | None = None) -> str:
    """Return a safe public logo URL from the supported environment variables."""
    env = environ if environ is not None else os.environ
    for name in LOGO_URL_ENV_VARS:
        value = str(env.get(name) or "").strip()
        if _is_safe_logo_url(value):
            return value
    return ""


def _is_safe_logo_url(value: str) -> bool:
    if not value:
        return False

    parsed = urlparse(value)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)

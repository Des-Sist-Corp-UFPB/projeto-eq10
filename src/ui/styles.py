"""Shared visual styling helpers for the Streamlit UI."""

from __future__ import annotations

import os
from typing import Any
from urllib.parse import urlparse

LOGO_URL_ENV_VARS = ("APP_LOGO_URL", "SIDEBAR_LOGO_URL", "MINIO_LOGO_URL")

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

[data-testid="stMarkdownContainer"],
[data-testid="stCaptionContainer"],
[data-testid="stText"],
[data-testid="stMetric"],
[data-testid="stWidgetLabel"],
[data-testid="stExpander"],
[data-testid="stDataFrame"],
[data-testid="stTable"],
[data-testid="stForm"],
[data-testid="stVerticalBlock"],
[data-testid="stHorizontalBlock"] {
    color: #111827 !important;
}

[data-testid="stSelectbox"] div[data-baseweb="select"] > div,
[data-testid="stTextInput"] input,
[data-testid="stDateInput"] input,
[data-testid="stNumberInput"] input,
[data-testid="stTextArea"] textarea,
[data-testid="stMultiSelect"] div[data-baseweb="select"] > div {
    background-color: #FFFFFF !important;
    color: #111827 !important;
    border-color: #CBD5E1 !important;
    box-shadow: none !important;
}

[data-testid="stSelectbox"] div[data-baseweb="select"] span,
[data-testid="stMultiSelect"] div[data-baseweb="select"] span,
[data-testid="stTextInput"] input::placeholder,
[data-testid="stDateInput"] input::placeholder,
[data-testid="stNumberInput"] input::placeholder,
[data-testid="stTextArea"] textarea::placeholder {
    color: #64748B !important;
}

[data-testid="stSelectbox"] label,
[data-testid="stTextInput"] label,
[data-testid="stDateInput"] label,
[data-testid="stNumberInput"] label,
[data-testid="stTextArea"] label,
[data-testid="stMultiSelect"] label {
    color: #111827 !important;
}

[data-testid="stSelectbox"] svg,
[data-testid="stDateInput"] svg,
[data-testid="stMultiSelect"] svg {
    color: #64748B !important;
    fill: #64748B !important;
}

div[data-baseweb="popover"] [role="listbox"],
div[data-baseweb="popover"] [role="listbox"] *,
div[data-baseweb="popover"] [data-baseweb="menu"],
div[data-baseweb="popover"] [data-baseweb="menu"] *,
div[data-baseweb="popover"] [data-baseweb="calendar"],
div[data-baseweb="popover"] [data-baseweb="calendar"] *,
[role="listbox"],
[role="listbox"] *,
[role="option"] {
    background-color: #FFFFFF !important;
    color: #111827 !important;
}

div[data-baseweb="popover"] [role="listbox"],
div[data-baseweb="popover"] [data-baseweb="menu"],
div[data-baseweb="popover"] [data-baseweb="calendar"] {
    border: 1px solid #E2E8F0 !important;
    box-shadow: 0 18px 36px rgba(15, 23, 42, 0.12) !important;
}

[role="option"]:hover,
[role="option"][aria-selected="true"] {
    background-color: #F1F5F9 !important;
}

[data-testid="stExpander"] details,
[data-testid="stForm"],
[data-testid="stDataFrame"],
[data-testid="stTable"] {
    background-color: #FFFFFF !important;
    border-color: #E2E8F0 !important;
    color: #111827 !important;
}

[data-testid="stDataFrame"] div,
[data-testid="stDataFrame"] span,
[data-testid="stDataFrame"] canvas,
[data-testid="stTable"] div,
[data-testid="stTable"] span,
[data-testid="stTable"] table,
[data-testid="stTable"] th,
[data-testid="stTable"] td {
    color: #111827 !important;
}

[data-testid="stDataFrame"] [role="grid"],
[data-testid="stDataFrame"] [role="row"],
[data-testid="stDataFrame"] [role="columnheader"],
[data-testid="stDataFrame"] [role="gridcell"],
[data-testid="stTable"] table,
[data-testid="stTable"] thead,
[data-testid="stTable"] tbody,
[data-testid="stTable"] tr,
[data-testid="stTable"] th,
[data-testid="stTable"] td {
    background-color: #FFFFFF !important;
}

</style>
"""

AUDIT_PAGE_CSS = """
<style>
/* Audit page polish for native Streamlit controls. Dynamic data is rendered by Streamlit widgets. */
[data-testid="stAppViewContainer"],
.stApp {
    background: #F8FAFC !important;
    color: #111827 !important;
}

[data-testid="stMetric"] {
    background: #FFFFFF !important;
    border: 1px solid #E2E8F0;
    border-radius: 0.75rem;
    padding: 0.72rem 0.85rem;
    box-shadow: 0 8px 18px rgba(15, 23, 42, 0.045);
}
[data-testid="stMetric"] label,
[data-testid="stMetric"] div,
[data-testid="stMetric"] p {
    color: #111827 !important;
}

[data-testid="stExpander"] details {
    background: #FFFFFF !important;
    border-color: #E2E8F0 !important;
    border-radius: 0.75rem !important;
    box-shadow: 0 8px 18px rgba(15, 23, 42, 0.04);
}
[data-testid="stExpander"] summary,
[data-testid="stExpander"] summary p,
[data-testid="stExpander"] label,
[data-testid="stExpander"] span,
[data-testid="stExpander"] p {
    color: #111827 !important;
}

[data-testid="stSelectbox"] div[data-baseweb="select"] > div,
[data-testid="stTextInput"] input,
[data-testid="stDateInput"] input {
    background: #FFFFFF !important;
    border-color: #CBD5E1 !important;
    color: #111827 !important;
    box-shadow: none !important;
}
[data-testid="stSelectbox"] div[data-baseweb="select"] span,
[data-testid="stTextInput"] input::placeholder,
[data-testid="stDateInput"] input::placeholder {
    color: #64748B !important;
}
[data-testid="stSelectbox"] label,
[data-testid="stTextInput"] label,
[data-testid="stDateInput"] label {
    color: #111827 !important;
}
[data-testid="stSelectbox"] svg,
[data-testid="stDateInput"] svg {
    color: #64748B !important;
    fill: #64748B !important;
}
[data-baseweb="popover"] [role="listbox"],
[data-baseweb="popover"] ul,
[data-baseweb="menu"] {
    background: #FFFFFF !important;
    color: #111827 !important;
    border: 1px solid #E2E8F0 !important;
}
[data-baseweb="popover"] [role="option"],
[data-baseweb="popover"] li {
    background: #FFFFFF !important;
    color: #111827 !important;
}
[data-baseweb="popover"] [role="option"]:hover,
[data-baseweb="popover"] li:hover {
    background: #F1F5F9 !important;
}

[data-testid="stDataFrame"] {
    background: #FFFFFF !important;
    border: 1px solid #E2E8F0 !important;
    border-radius: 0.75rem !important;
    box-shadow: 0 8px 18px rgba(15, 23, 42, 0.04);
    color: #111827 !important;
}
[data-testid="stDataFrame"] div,
[data-testid="stDataFrame"] span,
[data-testid="stDataFrame"] canvas {
    color: #111827 !important;
}
[data-testid="stDataFrame"] [role="grid"],
[data-testid="stDataFrame"] [role="row"],
[data-testid="stDataFrame"] [role="columnheader"],
[data-testid="stDataFrame"] [role="gridcell"] {
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

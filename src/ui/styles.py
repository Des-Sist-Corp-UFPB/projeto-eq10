"""Shared visual styling helpers for the Streamlit UI."""

from __future__ import annotations

import os
from typing import Any
from urllib.parse import urlparse, urlunparse

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
MINIO_LOGO_ENDPOINT_ENV_VARS = ("MINIO_LOGO_ENDPOINT",)
MINIO_LOGO_BUCKET_ENV_VARS = ("MINIO_LOGO_BUCKET",)
MINIO_LOGO_OBJECT_ENV_VARS = (
    "MINIO_LOGO_OBJECT",
    "MINIO_LOGO_FILENAME",
)
DEFAULT_MINIO_LOGO_BUCKET = "eq10"
DEFAULT_MINIO_LOGO_OBJECT = "logo.png"
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

/* BaseWeb renders select dropdowns, date-picker calendars and popovers in a portal
   appended to <body>, outside any page container. Page-scoped CSS below cannot reach
   them, so they are forced light here, globally, regardless of which page is active. */
[data-baseweb="popover"],
[data-baseweb="popover"] [data-baseweb="menu"],
[data-baseweb="calendar"],
ul[data-baseweb="menu"],
div[data-baseweb="menu"] {
    background: #FFFFFF !important;
    color: #111827 !important;
}

[data-baseweb="popover"] *,
[data-baseweb="calendar"] * {
    color: #111827 !important;
}

li[role="option"],
div[data-baseweb="menu"] li {
    background: #FFFFFF !important;
    color: #111827 !important;
}

li[role="option"]:hover,
li[role="option"][aria-selected="true"] {
    background: #F1F5F9 !important;
}

[data-testid="stDialog"],
[data-testid="stDialog"] [data-testid="stVerticalBlock"] {
    background: #FFFFFF !important;
    color: #111827 !important;
}

[data-testid="stDialog"] * {
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
    background-color: #FFFFFF !important;
    border-color: #E2E8F0 !important;
    border-radius: 0.75rem !important;
    box-shadow: 0 8px 18px rgba(15, 23, 42, 0.04);
}
.st-key-audit-page-shell [data-testid="stExpander"] summary {
    background: #FFFFFF !important;
    background-color: #FFFFFF !important;
    color: #111827 !important;
    border-radius: 0.75rem 0.75rem 0 0 !important;
}
.st-key-audit-page-shell [data-testid="stExpander"] details[open] summary {
    border-bottom: 1px solid #E2E8F0 !important;
}
.st-key-audit-page-shell [data-testid="stExpander"] summary p,
.st-key-audit-page-shell [data-testid="stExpander"] label,
.st-key-audit-page-shell [data-testid="stExpander"] span,
.st-key-audit-page-shell [data-testid="stExpander"] p {
    color: #111827 !important;
}
.st-key-audit-page-shell [data-testid="stExpander"] summary svg,
.st-key-audit-page-shell [data-testid="stExpander"] summary path {
    color: #64748B !important;
    fill: #64748B !important;
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
.st-key-audit-page-shell [data-testid="stDateInput"] [data-baseweb="input"],
.st-key-audit-page-shell [data-testid="stDateInput"] [data-baseweb="input"] > div,
.st-key-audit-page-shell [data-testid="stDateInput"] button {
    background: #FFFFFF !important;
    background-color: #FFFFFF !important;
    border-color: #CBD5E1 !important;
    color: #111827 !important;
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
.st-key-audit-page-shell [data-testid="stDataFrame"] [role="columnheader"] {
    background: #FFFFFF !important;
    background-color: #FFFFFF !important;
    color: #334155 !important;
    border-color: #E2E8F0 !important;
}
.st-key-audit-page-shell [data-testid="stDataFrame"] [role="columnheader"] *,
.st-key-audit-page-shell [data-testid="stDataFrame"] [role="columnheader"] button,
.st-key-audit-page-shell [data-testid="stDataFrame"] [role="columnheader"] svg,
.st-key-audit-page-shell [data-testid="stDataFrame"] [role="columnheader"] path {
    background-color: transparent !important;
    color: #334155 !important;
    fill: #334155 !important;
}
.st-key-audit-logs-dataframe [data-testid="stElementToolbar"] {
    display: none !important;
    visibility: hidden !important;
    pointer-events: none !important;
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
    """Return the configured public/signed logo URL without exposing MinIO credentials."""
    env = environ if environ is not None else os.environ
    for name in LOGO_URL_ENV_VARS:
        value = str(env.get(name) or "").strip()
        normalized_value = _normalize_logo_url(value)
        if normalized_value:
            return normalized_value

    built_url = _build_minio_logo_url(env)
    if built_url:
        return built_url

    return ""


def _build_minio_logo_url(env: dict[str, str]) -> str:
    endpoint = _first_env_value(env, MINIO_LOGO_ENDPOINT_ENV_VARS)
    if not endpoint:
        return ""

    parsed_endpoint = urlparse(endpoint.strip())
    if parsed_endpoint.scheme not in {"http", "https"} or not parsed_endpoint.netloc:
        return ""

    bucket = _first_env_value(env, MINIO_LOGO_BUCKET_ENV_VARS) or DEFAULT_MINIO_LOGO_BUCKET
    object_name = _first_env_value(env, MINIO_LOGO_OBJECT_ENV_VARS) or DEFAULT_MINIO_LOGO_OBJECT
    bucket = bucket.strip().strip("/")
    object_name = object_name.strip().lstrip("/")
    if not bucket or not object_name:
        return ""

    base_path = parsed_endpoint.path.rstrip("/")
    logo_path = f"{base_path}/{bucket}/{object_name}" if base_path else f"/{bucket}/{object_name}"
    return _normalize_logo_url(urlunparse(parsed_endpoint._replace(path=logo_path, params="", query="", fragment="")))


def _first_env_value(env: dict[str, str], names: tuple[str, ...]) -> str:
    for name in names:
        value = str(env.get(name) or "").strip()
        if value:
            return value
    return ""


def _normalize_logo_url(value: str) -> str:
    if not _is_safe_logo_url(value):
        return ""

    parsed = urlparse(value)
    path_parts = [part for part in parsed.path.split("/") if part]
    if path_parts and path_parts[0] == "browser":
        return ""

    return value


def _is_safe_logo_url(value: str) -> bool:
    if not value:
        return False

    parsed = urlparse(value)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)

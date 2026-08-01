"""GET /estatisticas — public statistics page (hero card + Power BI link card)."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

router = APIRouter()

POWERBI_URL = (
    "https://app.powerbi.com/view?r=eyJrIjoiMzMyNGZiMDgtNTk1Yy00Y2E4LTgyOTItMTU4MzNiYWUxMDg3IiwidCI6IjlkYmYzMjZlLTIxODUtNGM3OC1iY2NhLTBmNTdmOTc4ZjNkYSJ9"
)


@router.get("/estatisticas", response_class=HTMLResponse)
def get_estatisticas(request: Request) -> HTMLResponse:
    templates: Jinja2Templates = request.app.state.templates
    return templates.TemplateResponse(
        request,
        "estatisticas.html",
        {"active_page": "Estatísticas", "powerbi_url": POWERBI_URL},
    )

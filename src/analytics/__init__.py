"""Analytics de produto, isolado da observabilidade tecnica."""

from src.analytics.umami import (
    configure_umami,
    get_umami_status,
    track_event,
    track_event_once,
    track_page_view,
)

__all__ = [
    "configure_umami",
    "get_umami_status",
    "track_event",
    "track_event_once",
    "track_page_view",
]

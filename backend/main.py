"""ASGI entry point for the runnable architecture demos."""

from backend.incident_investigation.api import router as incident_router
from backend.research_workflow.api import app

app.include_router(incident_router)

__all__ = ["app"]

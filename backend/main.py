"""ASGI entry point for the runnable architecture demos."""

from backend.customer_support.api import router as support_router
from backend.incident_investigation.api import router as incident_router
from backend.internal_knowledge_action.api import router as knowledge_router
from backend.research_workflow.api import app

app.include_router(incident_router)
app.include_router(knowledge_router)
app.include_router(support_router)

__all__ = ["app"]

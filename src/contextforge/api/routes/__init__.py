"""
ContextForge API Routes Package
"""

from contextforge.api.routes.ingestion import router as ingestion_router
from contextforge.api.routes.mcp import router as mcp_router
from contextforge.api.routes.query import router as query_router

__all__ = ["ingestion_router", "query_router", "mcp_router"]

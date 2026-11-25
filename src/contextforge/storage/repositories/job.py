"""
ContextForge Job Repository (Compatibility Module)

Re-exports IngestionJobRepository as JobRepository for backward compatibility.
"""

from __future__ import annotations

from contextforge.storage.repositories.ingestion_job import IngestionJobRepository

JobRepository = IngestionJobRepository

__all__ = ["JobRepository"]

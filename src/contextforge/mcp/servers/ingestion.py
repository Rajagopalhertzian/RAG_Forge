"""
Ingestion MCP Server

Provides tools and resources for ingesting content from URLs and files.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import mimetypes
import uuid
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any

import httpx
from pydantic import BaseModel

from contextforge.config import get_settings
from contextforge.mcp.schema import (
    INGESTION_RESOURCES,
    INGESTION_TOOLS,
    ListResourcesResult,
    ListToolsResult,
    ResourceReadParams,
    ResourceReadResult,
    ToolCallParams,
    ToolCallResult,
    validate_tool_call,
)
from contextforge.storage.database import get_db_session
from contextforge.storage.repositories.chunk import ChunkRepository
from contextforge.storage.repositories.document import DocumentRepository
from contextforge.storage.repositories.ingestion_job import IngestionJobRepository as JobRepository


class JobStatus(str, Enum):
    """Ingestion job status."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class IngestUrlResponse(BaseModel):
    """Ingest URL tool response."""

    job_id: str
    status: JobStatus
    message: str


class IngestFileResponse(BaseModel):
    """Ingest file tool response."""

    job_id: str
    status: JobStatus
    message: str


class JobStatusResponse(BaseModel):
    """Ingestion job status response."""

    job_id: str
    status: JobStatus
    progress: float = 0.0
    documents_processed: int = 0
    chunks_created: int = 0
    error: str | None = None
    started_at: datetime
    completed_at: datetime | None = None


class IngestionServer:
    """
    Ingestion MCP Server.

    Provides tools for ingesting content from URLs and files.
    Stateless worker - all state managed by gateway.
    """

    def __init__(self):
        self.settings = get_settings()
        self._initialized = False
        self._http_client: httpx.AsyncClient | None = None

    async def initialize(self) -> None:
        """Initialize server connections."""
        if self._initialized:
            return

        self._http_client = httpx.AsyncClient(
            timeout=httpx.Timeout(60.0, connect=10.0),
            limits=httpx.Limits(max_connections=10, max_keepalive_connections=5),
        )
        self._initialized = True

    async def close(self) -> None:
        """Close server connections."""
        if self._http_client:
            await self._http_client.aclose()
        self._initialized = False

    # =========================================================================
    # Tool Implementations
    # =========================================================================

    async def ingest_url(
        self,
        url: str,
        collection: str = "default",
        metadata: dict[str, Any] | None = None,
    ) -> IngestUrlResponse:
        """
        Ingest content from a URL.

        Args:
            url: URL to ingest
            collection: Target collection name
            metadata: Optional metadata to attach

        Returns:
            IngestUrlResponse with job ID and status
        """
        if not self._initialized:
            await self.initialize()

        # Validate URL
        if not url.startswith(("http://", "https://")):
            return IngestUrlResponse(
                job_id="",
                status=JobStatus.FAILED,
                message="Invalid URL: must start with http:// or https://",
            )

        # Create job
        job_id = str(uuid.uuid4())
        job_meta = metadata or {}
        job_meta.update({"source": "url", "source_url": url, "collection": collection})

        # Store job in database
        try:
            async with get_db_session() as session:
                job_repo = JobRepository(session)
                await job_repo.create(
                    job_id=job_id,
                    job_type="ingest_url",
                    status=JobStatus.PENDING,
                    payload={"url": url, "collection": collection, "metadata": job_meta},
                )
        except Exception as e:
            return IngestUrlResponse(
                job_id="",
                status=JobStatus.FAILED,
                message=f"Failed to create job: {str(e)}",
            )

        # Start ingestion in background
        asyncio.create_task(self._process_url_ingestion(job_id, url, collection, job_meta))

        return IngestUrlResponse(
            job_id=job_id,
            status=JobStatus.PENDING,
            message="URL ingestion job created",
        )

    async def ingest_file(
        self,
        path: str,
        collection: str = "default",
        metadata: dict[str, Any] | None = None,
    ) -> IngestFileResponse:
        """
        Ingest content from a local file.

        Args:
            path: File path to ingest
            collection: Target collection name
            metadata: Optional metadata to attach

        Returns:
            IngestFileResponse with job ID and status
        """
        if not self._initialized:
            await self.initialize()

        # Validate file path
        file_path = Path(path)
        if not file_path.exists():
            return IngestFileResponse(
                job_id="",
                status=JobStatus.FAILED,
                message=f"File not found: {path}",
            )

        if not file_path.is_file():
            return IngestFileResponse(
                job_id="",
                status=JobStatus.FAILED,
                message=f"Path is not a file: {path}",
            )

        # Check file size
        file_size_mb = file_path.stat().st_size / (1024 * 1024)
        if file_size_mb > self.settings.INGESTION_MAX_FILE_SIZE_MB:
            return IngestFileResponse(
                job_id="",
                status=JobStatus.FAILED,
                message=f"File too large: {file_size_mb:.1f}MB (max {self.settings.INGESTION_MAX_FILE_SIZE_MB}MB)",
            )

        # Create job
        job_id = str(uuid.uuid4())
        job_meta = metadata or {}
        job_meta.update({
            "source": "file",
            "source_path": str(file_path),
            "file_name": file_path.name,
            "file_size": file_path.stat().st_size,
            "mime_type": mimetypes.guess_type(str(file_path))[0] or "application/octet-stream",
            "collection": collection,
        })

        # Store job in database
        try:
            async with get_db_session() as session:
                job_repo = JobRepository(session)
                await job_repo.create(
                    job_id=job_id,
                    job_type="ingest_file",
                    status=JobStatus.PENDING,
                    payload={"path": str(file_path), "collection": collection, "metadata": job_meta},
                )
        except Exception as e:
            return IngestFileResponse(
                job_id="",
                status=JobStatus.FAILED,
                message=f"Failed to create job: {str(e)}",
            )

        # Start ingestion in background
        asyncio.create_task(self._process_file_ingestion(job_id, file_path, collection, job_meta))

        return IngestFileResponse(
            job_id=job_id,
            status=JobStatus.PENDING,
            message="File ingestion job created",
        )

    async def ingest_status(self, job_id: str) -> JobStatusResponse:
        """
        Check the status of an ingestion job.

        Args:
            job_id: Ingestion job ID

        Returns:
            JobStatusResponse with job status and progress
        """
        if not self._initialized:
            await self.initialize()

        try:
            async with get_db_session() as session:
                job_repo = JobRepository(session)
                job = await job_repo.get_by_id(job_id)

                if not job:
                    return JobStatusResponse(
                        job_id=job_id,
                        status=JobStatus.FAILED,
                        error="Job not found",
                        started_at=datetime.utcnow(),
                    )

                return JobStatusResponse(
                    job_id=job.id,
                    status=JobStatus(job.status),
                    progress=job.progress or 0.0,
                    documents_processed=job.documents_processed or 0,
                    chunks_created=job.chunks_created or 0,
                    error=job.error,
                    started_at=job.started_at or datetime.utcnow(),
                    completed_at=job.completed_at,
                )
        except Exception as e:
            return JobStatusResponse(
                job_id=job_id,
                status=JobStatus.FAILED,
                error=str(e),
                started_at=datetime.utcnow(),
            )

    # =========================================================================
    # Background Processing
    # =========================================================================

    async def _process_url_ingestion(
        self,
        job_id: str,
        url: str,
        collection: str,
        metadata: dict[str, Any],
    ) -> None:
        """Process URL ingestion in background."""
        await self._update_job_status(job_id, JobStatus.RUNNING, progress=10.0)

        try:
            # Fetch content
            await self._update_job_status(job_id, JobStatus.RUNNING, progress=20.0)
            response = await self._http_client.get(url, follow_redirects=True)
            response.raise_for_status()
            content = response.text
            content_type = response.headers.get("content-type", "")

            await self._update_job_status(job_id, JobStatus.RUNNING, progress=40.0)

            # Extract text content based on content type
            if "text/html" in content_type:
                content = await self._extract_html_text(content)
            elif "application/pdf" in content_type:
                content = await self._extract_pdf_text(response.content)

            await self._update_job_status(job_id, JobStatus.RUNNING, progress=60.0)

            # Create document and chunks
            doc_id = await self._create_document_from_content(
                content=content,
                title=self._extract_title(content, url),
                collection=collection,
                metadata=metadata,
            )

            await self._update_job_status(
                job_id,
                JobStatus.RUNNING,
                progress=80.0,
                documents_processed=1,
            )

            # Chunk and embed (placeholder - would use actual chunking pipeline)
            chunks_created = await self._chunk_and_embed_document(doc_id, content)

            await self._update_job_status(
                job_id,
                JobStatus.COMPLETED,
                progress=100.0,
                documents_processed=1,
                chunks_created=chunks_created,
            )

        except Exception as e:
            await self._update_job_status(
                job_id,
                JobStatus.FAILED,
                error=str(e),
            )

    async def _process_file_ingestion(
        self,
        job_id: str,
        file_path: Path,
        collection: str,
        metadata: dict[str, Any],
    ) -> None:
        """Process file ingestion in background."""
        await self._update_job_status(job_id, JobStatus.RUNNING, progress=10.0)

        try:
            # Read file content
            mime_type = metadata.get("mime_type", "application/octet-stream")
            content = await self._read_file_content(file_path, mime_type)

            await self._update_job_status(job_id, JobStatus.RUNNING, progress=40.0)

            # Create document and chunks
            doc_id = await self._create_document_from_content(
                content=content,
                title=file_path.name,
                collection=collection,
                metadata=metadata,
            )

            await self._update_job_status(
                job_id,
                JobStatus.RUNNING,
                progress=60.0,
                documents_processed=1,
            )

            # Chunk and embed
            chunks_created = await self._chunk_and_embed_document(doc_id, content)

            await self._update_job_status(
                job_id,
                JobStatus.COMPLETED,
                progress=100.0,
                documents_processed=1,
                chunks_created=chunks_created,
            )

        except Exception as e:
            await self._update_job_status(
                job_id,
                JobStatus.FAILED,
                error=str(e),
            )

    async def _update_job_status(
        self,
        job_id: str,
        status: JobStatus,
        progress: float | None = None,
        documents_processed: int | None = None,
        chunks_created: int | None = None,
        error: str | None = None,
    ) -> None:
        """Update job status in database."""
        try:
            async with get_db_session() as session:
                job_repo = JobRepository(session)
                await job_repo.update_status(
                    job_id=job_id,
                    status=status.value,
                    progress=progress,
                    documents_processed=documents_processed,
                    chunks_created=chunks_created,
                    error=error,
                )
        except Exception:
            pass  # Log error but don't fail the ingestion

    async def _extract_html_text(self, html: str) -> str:
        """Extract text from HTML."""
        try:
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(html, "html.parser")
            # Remove script and style elements
            for script in soup(["script", "style", "nav", "footer", "header"]):
                script.decompose()
            return soup.get_text(separator="\n", strip=True)
        except Exception:
            return html

    async def _extract_pdf_text(self, pdf_bytes: bytes) -> str:
        """Extract text from PDF."""
        try:
            import io

            import pypdf
            pdf_file = io.BytesIO(pdf_bytes)
            reader = pypdf.PdfReader(pdf_file)
            text_parts = []
            for page in reader.pages:
                text_parts.append(page.extract_text())
            return "\n\n".join(text_parts)
        except Exception:
            return ""

    def _extract_title(self, content: str, url: str) -> str:
        """Extract title from content or URL."""
        # Try to find title in first few lines
        lines = content.strip().split("\n")
        for line in lines[:5]:
            line = line.strip()
            if line and len(line) < 200:
                return line
        # Fallback to URL
        return url

    async def _read_file_content(self, file_path: Path, mime_type: str) -> str:
        """Read file content based on MIME type."""
        if mime_type.startswith("text/"):
            return file_path.read_text(encoding="utf-8", errors="ignore")
        elif mime_type == "application/pdf":
            import pypdf
            with open(file_path, "rb") as f:
                reader = pypdf.PdfReader(f)
                text_parts = []
                for page in reader.pages:
                    text_parts.append(page.extract_text())
                return "\n\n".join(text_parts)
        elif mime_type in ("application/msword", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"):
            try:
                import docx
                doc = docx.Document(file_path)
                return "\n".join([p.text for p in doc.paragraphs])
            except Exception:
                return ""
        else:
            # Try to read as text
            return file_path.read_text(encoding="utf-8", errors="ignore")

    async def _create_document_from_content(
        self,
        content: str,
        title: str,
        collection: str,
        metadata: dict[str, Any],
    ) -> str:
        """Create document in database."""
        doc_id = str(uuid.uuid4())
        doc_metadata = metadata.copy()
        doc_metadata.update({
            "collection": collection,
            "title": title,
            "content_hash": hashlib.sha256(content.encode()).hexdigest()[:16],
        })

        try:
            async with get_db_session() as session:
                doc_repo = DocumentRepository(session)
                await doc_repo.create(
                    id=doc_id,
                    title=title,
                    content=content,
                    metadata=doc_metadata,
                )
        except Exception:
            pass  # Log error

        return doc_id

    async def _chunk_and_embed_document(self, doc_id: str, content: str) -> int:
        """Chunk document and create embeddings (placeholder)."""
        # This would integrate with the actual chunking pipeline
        # For now, return a mock count
        chunk_count = max(1, len(content) // 1000)

        try:
            async with get_db_session() as session:
                chunk_repo = ChunkRepository(session)
                # Create mock chunks
                for i in range(chunk_count):
                    start = i * 1000
                    end = min(start + 1000, len(content))
                    chunk_content = content[start:end]
                    await chunk_repo.create(
                        document_id=doc_id,
                        content=chunk_content,
                        chunk_index=i,
                        metadata={"source": "mcp_ingestion"},
                    )
        except Exception:
            pass

        return chunk_count

    # =========================================================================
    # Resource Implementations
    # =========================================================================

    async def read_job_resource(self, job_id: str) -> ResourceReadResult:
        """Read job resource."""
        status = await self.ingest_status(job_id)
        return ResourceReadResult(
            contents=[
                {
                    "uri": f"job://{job_id}",
                    "mimeType": "application/json",
                    "text": status.model_dump_json(),
                }
            ]
        )

    # =========================================================================
    # MCP Protocol Handlers
    # =========================================================================

    async def handle_tool_call(self, params: ToolCallParams) -> ToolCallResult:
        """Handle tool call from MCP protocol."""
        valid, error = validate_tool_call(params.name, params.arguments)
        if not valid:
            return ToolCallResult(
                content=[{"type": "text", "text": error or "Invalid tool call"}],
                isError=True,
            )

        try:
            if params.name == "ingest_url":
                result = await self.ingest_url(**params.arguments)
                return ToolCallResult(
                    content=[{"type": "text", "text": result.model_dump_json()}],
                    structuredContent=result.model_dump(),
                )
            elif params.name == "ingest_file":
                result = await self.ingest_file(**params.arguments)
                return ToolCallResult(
                    content=[{"type": "text", "text": result.model_dump_json()}],
                    structuredContent=result.model_dump(),
                )
            elif params.name == "ingest_status":
                result = await self.ingest_status(**params.arguments)
                return ToolCallResult(
                    content=[{"type": "text", "text": result.model_dump_json()}],
                    structuredContent=result.model_dump(),
                )
            else:
                return ToolCallResult(
                    content=[{"type": "text", "text": f"Unknown tool: {params.name}"}],
                    isError=True,
                )
        except Exception as e:
            return ToolCallResult(
                content=[{"type": "text", "text": f"Tool execution error: {str(e)}"}],
                isError=True,
            )

    async def handle_resource_read(self, params: ResourceReadParams) -> ResourceReadResult:
        """Handle resource read from MCP protocol."""
        uri = params.uri

        if uri.startswith("job://"):
            job_id = uri[len("job://"):]
            return await self.read_job_resource(job_id)
        else:
            return ResourceReadResult(
                contents=[
                    {
                        "uri": uri,
                        "mimeType": "application/json",
                        "text": json.dumps({"error": f"Unknown resource URI: {uri}"}),
                    }
                ]
            )

    def get_tools(self) -> ListToolsResult:
        """Get list of available tools."""
        return ListToolsResult(tools=INGESTION_TOOLS)

    def get_resources(self) -> ListResourcesResult:
        """Get list of available resources."""
        return ListResourcesResult(resources=INGESTION_RESOURCES)


# Global server instance
_ingestion_server: IngestionServer | None = None


async def get_ingestion_server() -> IngestionServer:
    """Get or create ingestion server instance."""
    global _ingestion_server
    if _ingestion_server is None:
        _ingestion_server = IngestionServer()
        await _ingestion_server.initialize()
    return _ingestion_server


async def close_ingestion_server() -> None:
    """Close ingestion server instance."""
    global _ingestion_server
    if _ingestion_server:
        await _ingestion_server.close()
        _ingestion_server = None

"""
ContextForge PDF Loader

Loads PDF documents using pypdf.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import aiofiles
from pypdf import PdfReader

from contextforge.ingestion.loaders.base import (
    BaseLoader,
    DocumentContent,
    LoaderConfig,
    LoaderRegistry,
)


class PDFLoaderConfig(LoaderConfig):
    """Configuration for PDF loader."""

    extract_images: bool = False
    page_separator: str = "\n\n---PAGE BREAK---\n\n"


@LoaderRegistry.register
class PDFLoader(BaseLoader):
    """Loader for PDF documents."""

    source_type = "pdf"

    def __init__(self, config: PDFLoaderConfig | None = None):
        super().__init__(config or PDFLoaderConfig())

    async def load(self, source_id: str, **kwargs: Any) -> DocumentContent:
        """Load a single PDF file."""
        path = Path(source_id)
        if not path.exists():
            raise FileNotFoundError(f"PDF file not found: {source_id}")

        # Check file size
        file_size_mb = path.stat().st_size / (1024 * 1024)
        if file_size_mb > self.config.max_file_size_mb:
            raise ValueError(f"File too large: {file_size_mb:.1f}MB > {self.config.max_file_size_mb}MB")

        content_parts = []
        metadata: dict[str, Any] = {}

        # Read PDF
        async with aiofiles.open(path, "rb") as f:
            content = await f.read()

        reader = PdfReader(content)
        metadata["page_count"] = len(reader.pages)
        metadata["pdf_metadata"] = reader.metadata or {}

        for i, page in enumerate(reader.pages):
            text = page.extract_text()
            if text:
                content_parts.append(text)

        full_content = self.config.page_separator.join(content_parts)

        return DocumentContent(
            content=full_content,
            metadata=self._create_metadata(**metadata),
            source_id=str(path.absolute()),
            title=path.stem,
        )

    async def load_many(self, source_ids: list[str], **kwargs: Any) -> AsyncIterator[DocumentContent]:
        """Load multiple PDF files."""
        for source_id in source_ids:
            try:
                yield await self.load(source_id, **kwargs)
            except Exception as e:
                # Log error and continue
                yield DocumentContent(
                    content="",
                    metadata=self._create_metadata(error=str(e), source_id=source_id),
                    source_id=source_id,
                    title=Path(source_id).stem,
                )

    async def validate_source(self, source_id: str) -> bool:
        """Validate PDF file exists and is readable."""
        path = Path(source_id)
        if not path.exists() or not path.is_file():
            return False
        if path.suffix.lower() != ".pdf":
            return False
        try:
            async with aiofiles.open(path, "rb") as f:
                content = await f.read(1024)
            return content.startswith(b"%PDF")
        except Exception:
            return False

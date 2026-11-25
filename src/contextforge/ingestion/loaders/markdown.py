"""
ContextForge Markdown Loader

Loads Markdown documents with frontmatter support.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import aiofiles
import frontmatter
import markdown

from contextforge.ingestion.loaders.base import (
    BaseLoader,
    DocumentContent,
    LoaderConfig,
    LoaderRegistry,
)


class MarkdownLoaderConfig(LoaderConfig):
    """Configuration for Markdown loader."""

    extract_frontmatter: bool = True
    convert_to_html: bool = False
    heading_separator: str = "\n\n"


@LoaderRegistry.register
class MarkdownLoader(BaseLoader):
    """Loader for Markdown documents."""

    source_type = "markdown"

    def __init__(self, config: MarkdownLoaderConfig | None = None):
        super().__init__(config or MarkdownLoaderConfig())

    async def load(self, source_id: str, **kwargs: Any) -> DocumentContent:
        """Load a single Markdown file."""
        path = Path(source_id)
        if not path.exists():
            raise FileNotFoundError(f"Markdown file not found: {source_id}")

        # Check file size
        file_size_mb = path.stat().st_size / (1024 * 1024)
        if file_size_mb > self.config.max_file_size_mb:
            raise ValueError(f"File too large: {file_size_mb:.1f}MB > {self.config.max_file_size_mb}MB")

        async with aiofiles.open(path, encoding=self.config.encoding) as f:
            content = await f.read()

        # Parse frontmatter
        post = frontmatter.loads(content)
        metadata = dict(post.metadata) if self.config.extract_frontmatter else {}
        md_content = post.content

        # Extract title from frontmatter or first heading
        title = metadata.get("title")
        if not title:
            # Extract from first heading in markdown content
            import re
            heading_match = re.search(r"^#\s+(.+)$", md_content, re.MULTILINE)
            if heading_match:
                title = heading_match.group(1).strip()
            else:
                title = path.stem

        # Optionally convert to HTML
        if self.config.convert_to_html:
            md_content = markdown.markdown(md_content, extensions=["tables", "fenced_code", "toc"])

        return DocumentContent(
            content=md_content,
            metadata=self._create_metadata(**metadata),
            source_id=str(path.absolute()),
            title=title,
        )

    async def load_many(self, source_ids: list[str], **kwargs: Any) -> AsyncIterator[DocumentContent]:
        """Load multiple Markdown files."""
        for source_id in source_ids:
            try:
                yield await self.load(source_id, **kwargs)
            except Exception as e:
                yield DocumentContent(
                    content="",
                    metadata=self._create_metadata(error=str(e), source_id=source_id),
                    source_id=source_id,
                    title=Path(source_id).stem,
                )

    async def validate_source(self, source_id: str) -> bool:
        """Validate Markdown file exists."""
        path = Path(source_id)
        return path.exists() and path.is_file() and path.suffix.lower() in (".md", ".markdown", ".mdx")

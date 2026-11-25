"""
ContextForge Confluence Loader

Loads pages from Confluence using the REST API.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup

from contextforge.config import settings
from contextforge.ingestion.loaders.base import (
    BaseLoader,
    DocumentContent,
    LoaderConfig,
    LoaderRegistry,
)


class ConfluenceLoaderConfig(LoaderConfig):
    """Configuration for Confluence loader."""

    max_pages: int = 1000
    include_attachments: bool = False


@LoaderRegistry.register
class ConfluenceLoader(BaseLoader):
    """Loader for Confluence pages."""

    source_type = "confluence"

    def __init__(self, config: ConfluenceLoaderConfig | None = None):
        super().__init__(config or ConfluenceLoaderConfig())
        self.base_url = settings.CONFLUENCE_URL
        self.username = settings.CONFLUENCE_USERNAME
        self.api_token = settings.CONFLUENCE_API_TOKEN
        self._client: httpx.AsyncClient | None = None

    @property
    def client(self) -> httpx.AsyncClient:
        """Get or create HTTP client with auth."""
        if self._client is None:
            self._client = httpx.AsyncClient(
                auth=(self.username, self.api_token),
                headers={
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                },
                timeout=30.0,
            )
        return self._client

    async def close(self) -> None:
        """Close HTTP client."""
        if self._client:
            await self._client.aclose()
            self._client = None

    def _html_to_text(self, html: str) -> str:
        """Convert Confluence HTML to plain text."""
        soup = BeautifulSoup(html, "html.parser")

        # Remove script and style elements
        for script in soup(["script", "style"]):
            script.decompose()

        # Convert common Confluence elements
        for macro in soup.find_all("ac:structured-macro"):
            macro_name = macro.get("ac:name", "")
            if macro_name == "code":
                code_body = macro.find("ac:plain-text-body")
                if code_body:
                    macro.replace_with(f"\n```\n{code_body.get_text()}\n```\n")
            elif macro_name == "info" or macro_name == "note" or macro_name == "warning":
                macro.replace_with(f"\n> [{macro_name.upper()}] {macro.get_text()}\n")
            else:
                macro.decompose()

        # Get text
        text = soup.get_text(separator="\n", strip=True)

        # Clean up excessive newlines
        import re
        text = re.sub(r"\n{3,}", "\n\n", text)

        return text

    async def _fetch_page(self, page_id: str) -> dict[str, Any]:
        """Fetch a single page from Confluence."""
        url = urljoin(self.base_url, f"/rest/api/content/{page_id}")
        params = {
            "expand": "body.storage,version,space,metadata.labels",
        }
        response = await self.client.get(url, params=params)
        response.raise_for_status()
        return response.json()

    async def _fetch_children(self, page_id: str) -> list[dict[str, Any]]:
        """Fetch child pages."""
        url = urljoin(self.base_url, f"/rest/api/content/{page_id}/child/page")
        params = {"limit": 100, "expand": "body.storage,version"}
        children = []

        while True:
            response = await self.client.get(url, params=params)
            response.raise_for_status()
            data = response.json()
            children.extend(data.get("results", []))

            if "_links" in data and "next" in data["_links"]:
                url = urljoin(self.base_url, data["_links"]["next"])
            else:
                break

        return children

    async def _page_to_content(self, page: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        """Convert Confluence page to content and metadata."""
        # Extract body
        body = page.get("body", {}).get("storage", {}).get("value", "")
        content = self._html_to_text(body)

        # Metadata
        metadata = {
            "confluence_page_id": page["id"],
            "confluence_title": page.get("title", ""),
            "confluence_space_key": page.get("space", {}).get("key", ""),
            "confluence_space_name": page.get("space", {}).get("name", ""),
            "confluence_version": page.get("version", {}).get("number", 0),
            "confluence_created": page.get("version", {}).get("when", ""),
            "confluence_author": page.get("version", {}).get("by", {}).get("displayName", ""),
            "confluence_url": urljoin(self.base_url, page.get("_links", {}).get("webui", "")),
            "confluence_labels": [l["name"] for l in page.get("metadata", {}).get("labels", {}).get("results", [])],
        }

        return content, metadata

    async def load(self, source_id: str, **kwargs: Any) -> DocumentContent:
        """Load a single Confluence page."""
        page = await self._fetch_page(source_id)
        content, metadata = await self._page_to_content(page)

        return DocumentContent(
            content=content,
            metadata=self._create_metadata(**metadata),
            source_id=source_id,
            title=metadata.get("confluence_title", "Untitled"),
        )

    async def load_many(self, source_ids: list[str], **kwargs: Any) -> AsyncIterator[DocumentContent]:
        """Load multiple Confluence pages."""
        for source_id in source_ids:
            try:
                yield await self.load(source_id, **kwargs)
            except Exception as e:
                yield DocumentContent(
                    content="",
                    metadata=self._create_metadata(error=str(e), source_id=source_id),
                    source_id=source_id,
                    title="Error",
                )

    async def validate_source(self, source_id: str) -> bool:
        """Validate Confluence page exists."""
        try:
            await self._fetch_page(source_id)
            return True
        except Exception:
            return False

    async def load_space(self, space_key: str, **kwargs: Any) -> AsyncIterator[DocumentContent]:
        """Load all pages from a Confluence space."""
        url = urljoin(self.base_url, "/rest/api/content")
        params = {
            "spaceKey": space_key,
            "limit": 100,
            "expand": "body.storage,version,space,metadata.labels",
        }
        count = 0

        while count < self.config.max_pages:
            response = await self.client.get(url, params=params)
            response.raise_for_status()
            data = response.json()

            for page in data.get("results", []):
                if count >= self.config.max_pages:
                    break
                try:
                    content, metadata = await self._page_to_content(page)
                    yield DocumentContent(
                        content=content,
                        metadata=self._create_metadata(**metadata),
                        source_id=page["id"],
                        title=metadata.get("confluence_title", "Untitled"),
                    )
                    count += 1
                except Exception as e:
                    yield DocumentContent(
                        content="",
                        metadata=self._create_metadata(error=str(e), source_id=page["id"]),
                        source_id=page["id"],
                        title="Error",
                    )

            if "_links" in data and "next" in data["_links"]:
                url = urljoin(self.base_url, data["_links"]["next"])
                params = {}
            else:
                break

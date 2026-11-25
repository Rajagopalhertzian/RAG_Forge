"""
ContextForge Notion Loader

Loads pages from Notion using the Notion API.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import httpx

from contextforge.config import settings
from contextforge.ingestion.loaders.base import (
    BaseLoader,
    DocumentContent,
    LoaderConfig,
    LoaderRegistry,
)


class NotionLoaderConfig(LoaderConfig):
    """Configuration for Notion loader."""

    api_version: str = "2022-06-28"
    max_pages: int = 1000


@LoaderRegistry.register
class NotionLoader(BaseLoader):
    """Loader for Notion pages."""

    source_type = "notion"

    def __init__(self, config: NotionLoaderConfig | None = None):
        super().__init__(config or NotionLoaderConfig())
        self.api_key = settings.NOTION_API_KEY
        self.api_version = self.config.api_version
        self.base_url = "https://api.notion.com/v1"
        self._client: httpx.AsyncClient | None = None

    @property
    def client(self) -> httpx.AsyncClient:
        """Get or create HTTP client."""
        if self._client is None:
            self._client = httpx.AsyncClient(
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Notion-Version": self.api_version,
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

    def _block_to_text(self, block: dict[str, Any]) -> str:
        """Convert Notion block to text."""
        block_type = block.get("type", "")
        content = ""

        if block_type == "paragraph":
            rich_text = block.get("paragraph", {}).get("rich_text", [])
            content = "".join([t.get("plain_text", "") for t in rich_text])
        elif block_type in ("heading_1", "heading_2", "heading_3"):
            rich_text = block.get(block_type, {}).get("rich_text", [])
            content = "#" * int(block_type[-1]) + " " + "".join([t.get("plain_text", "") for t in rich_text])
        elif block_type == "bulleted_list_item":
            rich_text = block.get("bulleted_list_item", {}).get("rich_text", [])
            content = "- " + "".join([t.get("plain_text", "") for t in rich_text])
        elif block_type == "numbered_list_item":
            rich_text = block.get("numbered_list_item", {}).get("rich_text", [])
            content = "1. " + "".join([t.get("plain_text", "") for t in rich_text])
        elif block_type == "code":
            code = block.get("code", {})
            rich_text = code.get("rich_text", [])
            language = code.get("language", "")
            content = f"```{language}\n" + "".join([t.get("plain_text", "") for t in rich_text]) + "\n```"
        elif block_type == "quote":
            rich_text = block.get("quote", {}).get("rich_text", [])
            content = "> " + "".join([t.get("plain_text", "") for t in rich_text])
        elif block_type == "callout":
            rich_text = block.get("callout", {}).get("rich_text", [])
            content = "> [!NOTE]\n> " + "".join([t.get("plain_text", "") for t in rich_text])
        elif block_type == "divider":
            content = "---"
        elif block_type == "image":
            image = block.get("image", {})
            url = image.get("external", {}).get("url") or image.get("file", {}).get("url", "")
            caption = "".join([t.get("plain_text", "") for t in image.get("caption", [])])
            content = f"![{caption}]({url})"
        elif block_type == "bookmark":
            bookmark = block.get("bookmark", {})
            url = bookmark.get("url", "")
            content = f"[Bookmark]({url})"
        elif block_type == "embed":
            embed = block.get("embed", {})
            url = embed.get("url", "")
            content = f"[Embed]({url})"
        elif block_type == "child_page":
            page = block.get("child_page", {})
            content = f"[Sub-page: {page.get('title', '')}]"
        elif block_type == "child_database":
            db = block.get("child_database", {})
            content = f"[Database: {db.get('title', '')}]"
        elif block_type == "table":
            content = "[Table]"
        elif block_type == "table_row":
            cells = block.get("table_row", {}).get("cells", [])
            content = "| " + " | ".join(["".join([t.get("plain_text", "") for t in cell]) for cell in cells]) + " |"
        elif block_type == "column_list":
            content = ""
        elif block_type == "column":
            content = ""
        elif block_type == "synced_block":
            content = ""
        elif block_type == "link_preview":
            url = block.get("link_preview", {}).get("url", "")
            content = f"[Link Preview]({url})"
        elif block_type == "template":
            content = ""
        else:
            # Try to extract any rich_text
            for key, value in block.items():
                if isinstance(value, dict) and "rich_text" in value:
                    rich_text = value["rich_text"]
                    content = "".join([t.get("plain_text", "") for t in rich_text])
                    break

        # Recursively process children
        if block.get("has_children"):
            children = self._get_children(block["id"])
            if children:
                child_texts = [self._block_to_text(child) for child in children]
                content += "\n" + "\n".join(child_texts)

        return content

    def _get_children(self, block_id: str) -> list[dict[str, Any]]:
        """Get child blocks (synchronous for recursion)."""
        # This would need async in real implementation
        # For now, return empty
        return []

    async def _fetch_page(self, page_id: str) -> dict[str, Any]:
        """Fetch a single page from Notion."""
        response = await self.client.get(f"{self.base_url}/pages/{page_id}")
        response.raise_for_status()
        return response.json()

    async def _fetch_blocks(self, block_id: str) -> list[dict[str, Any]]:
        """Fetch all blocks for a page."""
        blocks = []
        cursor = None

        while True:
            params = {"page_size": 100}
            if cursor:
                params["start_cursor"] = cursor

            response = await self.client.get(
                f"{self.base_url}/blocks/{block_id}/children",
                params=params,
            )
            response.raise_for_status()
            data = response.json()

            blocks.extend(data.get("results", []))

            if not data.get("has_more"):
                break
            cursor = data.get("next_cursor")

        return blocks

    async def _page_to_markdown(self, page: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        """Convert Notion page to markdown."""
        properties = page.get("properties", {})
        title = ""

        # Extract title from properties
        for prop_name, prop_value in properties.items():
            if prop_value.get("type") == "title":
                title = "".join([t.get("plain_text", "") for t in prop_value.get("title", [])])
                break

        # Get blocks
        blocks = await self._fetch_blocks(page["id"])

        # Convert blocks to text
        content_parts = []
        for block in blocks:
            text = self._block_to_text(block)
            if text:
                content_parts.append(text)

        content = "\n\n".join(content_parts)

        # Metadata
        metadata = {
            "notion_page_id": page["id"],
            "notion_created_time": page.get("created_time"),
            "notion_last_edited_time": page.get("last_edited_time"),
            "notion_url": page.get("url"),
            "notion_properties": properties,
        }

        return content, metadata

    async def load(self, source_id: str, **kwargs: Any) -> DocumentContent:
        """Load a single Notion page."""
        page = await self._fetch_page(source_id)
        content, metadata = await self._page_to_markdown(page)

        return DocumentContent(
            content=content,
            metadata=self._create_metadata(**metadata),
            source_id=source_id,
            title=metadata.get("notion_properties", {}).get("title", {}).get("title", [{}])[0].get("plain_text", "Untitled"),
        )

    async def load_many(self, source_ids: list[str], **kwargs: Any) -> AsyncIterator[DocumentContent]:
        """Load multiple Notion pages."""
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
        """Validate Notion page exists."""
        try:
            await self._fetch_page(source_id)
            return True
        except Exception:
            return False

    async def load_database(self, database_id: str, **kwargs: Any) -> AsyncIterator[DocumentContent]:
        """Load all pages from a Notion database."""
        cursor = None
        count = 0

        while count < self.config.max_pages:
            params = {"page_size": 100}
            if cursor:
                params["start_cursor"] = cursor

            response = await self.client.post(
                f"{self.base_url}/databases/{database_id}/query",
                json=params,
            )
            response.raise_for_status()
            data = response.json()

            for page in data.get("results", []):
                if count >= self.config.max_pages:
                    break
                try:
                    yield await self.load(page["id"], **kwargs)
                    count += 1
                except Exception as e:
                    yield DocumentContent(
                        content="",
                        metadata=self._create_metadata(error=str(e), source_id=page["id"]),
                        source_id=page["id"],
                        title="Error",
                    )

            if not data.get("has_more"):
                break
            cursor = data.get("next_cursor")

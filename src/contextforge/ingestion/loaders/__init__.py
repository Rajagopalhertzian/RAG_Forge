"""
ContextForge Loaders Package

Document loaders for various sources.
"""

from contextforge.ingestion.loaders.base import (
    BaseLoader,
    DocumentContent,
    LoaderConfig,
    LoaderRegistry,
)
from contextforge.ingestion.loaders.confluence import ConfluenceLoader, ConfluenceLoaderConfig
from contextforge.ingestion.loaders.github import GitHubLoader, GitHubLoaderConfig
from contextforge.ingestion.loaders.markdown import MarkdownLoader, MarkdownLoaderConfig
from contextforge.ingestion.loaders.notion import NotionLoader, NotionLoaderConfig
from contextforge.ingestion.loaders.pdf import PDFLoader, PDFLoaderConfig
from contextforge.ingestion.loaders.slack import SlackLoader, SlackLoaderConfig

__all__ = [
    "BaseLoader",
    "DocumentContent",
    "LoaderConfig",
    "LoaderRegistry",
    "PDFLoader",
    "PDFLoaderConfig",
    "MarkdownLoader",
    "MarkdownLoaderConfig",
    "NotionLoader",
    "NotionLoaderConfig",
    "ConfluenceLoader",
    "ConfluenceLoaderConfig",
    "GitHubLoader",
    "GitHubLoaderConfig",
    "SlackLoader",
    "SlackLoaderConfig",
]

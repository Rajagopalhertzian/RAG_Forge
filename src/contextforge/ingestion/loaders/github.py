"""
ContextForge GitHub Loader

Loads files from GitHub repositories using the GitHub API.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any, Union

import githubkit
from githubkit_schemas.v2026_03_10.models import (
    ContentDirectoryItems,
    ContentFile,
    ContentSubmodule,
    ContentSymlink,
)

# Type alias for the union of content types returned by GitHub API
RepositoryContent = Union[ContentFile, ContentDirectoryItems, ContentSymlink, ContentSubmodule]

from contextforge.config import settings
from contextforge.ingestion.loaders.base import (
    BaseLoader,
    DocumentContent,
    LoaderConfig,
    LoaderRegistry,
)


class GitHubLoaderConfig(LoaderConfig):
    """Configuration for GitHub loader."""

    max_files: int = 1000
    file_extensions: list[str] = [
        ".py", ".js", ".ts", ".jsx", ".tsx", ".java", ".go", ".rs",
        ".cpp", ".c", ".h", ".hpp", ".cs", ".php", ".rb", ".swift",
        ".kt", ".scala", ".clj", ".fs", ".ml", ".ex", ".exs",
        ".md", ".mdx", ".rst", ".txt", ".json", ".yaml", ".yml",
        ".toml", ".ini", ".cfg", ".conf", ".config",
        ".sql", ".graphql", ".proto", ".avsc",
        ".dockerfile", ".dockerignore", ".gitignore",
        ".sh", ".bash", ".zsh", ".fish",
        ".ps1", ".bat", ".cmd",
    ]
    exclude_patterns: list[str] = [
        "**/node_modules/**",
        "**/dist/**",
        "**/build/**",
        "**/.git/**",
        "**/__pycache__/**",
        "**/*.min.js",
        "**/*.min.css",
        "**/vendor/**",
        "**/target/**",
    ]


@LoaderRegistry.register
class GitHubLoader(BaseLoader):
    """Loader for GitHub repository files."""

    source_type = "github"

    def __init__(self, config: GitHubLoaderConfig | None = None):
        super().__init__(config or GitHubLoaderConfig())
        self.token = settings.GITHUB_TOKEN
        self.org = settings.GITHUB_ORG
        self._client: githubkit.GitHub | None = None

    @property
    def client(self) -> githubkit.GitHub:
        """Get or create GitHub client."""
        if self._client is None:
            self._client = githubkit.GitHub(self.token)
        return self._client

    def _should_process_file(self, path: str) -> bool:
        """Check if file should be processed."""
        # Check exclude patterns
        import fnmatch
        for pattern in self.config.exclude_patterns:
            if fnmatch.fnmatch(path, pattern):
                return False

        # Check extensions
        if not any(path.endswith(ext) for ext in self.config.file_extensions):
            # Allow files without extension if they're common config files
            filename = path.split("/")[-1]
            if filename not in ["Dockerfile", "Makefile", "LICENSE", "README", "CHANGELOG", "CONTRIBUTING"]:
                return False

        return True

    async def _fetch_repo_contents(
        self,
        owner: str,
        repo: str,
        path: str = "",
        ref: str | None = None,
    ) -> list[RepositoryContent]:
        """Fetch repository contents recursively."""
        params = {}
        if ref:
            params["ref"] = ref

        response = await self.client.rest.repos.get_content(owner, repo, path, **params)
        return response.parsed_data if isinstance(response.parsed_data, list) else [response.parsed_data]

    async def _fetch_file_content(self, owner: str, repo: str, path: str, ref: str | None = None) -> str:
        """Fetch raw file content."""
        params = {}
        if ref:
            params["ref"] = ref

        response = await self.client.rest.repos.get_content(owner, repo, path, **params)
        content = response.parsed_data

        if isinstance(content, list):
            raise ValueError(f"Path {path} is a directory, not a file")

        # Content is base64 encoded
        import base64
        return base64.b64decode(content.content).decode("utf-8", errors="replace")

    async def load_repo(
        self,
        owner: str,
        repo: str,
        ref: str | None = None,
        path: str = "",
    ) -> AsyncIterator[DocumentContent]:
        """Load all files from a repository."""
        count = 0
        queue = [(path, ref)]

        while queue and count < self.config.max_files:
            current_path, current_ref = queue.pop(0)

            try:
                contents = await self._fetch_repo_contents(owner, repo, current_path, current_ref)

                for item in contents:
                    if count >= self.config.max_files:
                        break

                    if item.type == "dir":
                        queue.append((item.path, current_ref))
                    elif item.type == "file" and self._should_process_file(item.path):
                        try:
                            file_content = await self._fetch_file_content(owner, repo, item.path, current_ref)

                            metadata = {
                                "github_owner": owner,
                                "github_repo": repo,
                                "github_path": item.path,
                                "github_sha": item.sha,
                                "github_size": item.size,
                                "github_ref": current_ref or "default",
                                "github_url": item.html_url,
                            }

                            yield DocumentContent(
                                content=file_content,
                                metadata=self._create_metadata(**metadata),
                                source_id=f"{owner}/{repo}/{item.path}",
                                title=item.path.split("/")[-1],
                            )
                            count += 1
                        except Exception as e:
                            yield DocumentContent(
                                content="",
                                metadata=self._create_metadata(
                                    error=str(e),
                                    github_owner=owner,
                                    github_repo=repo,
                                    github_path=item.path,
                                ),
                                source_id=f"{owner}/{repo}/{item.path}",
                                title=item.path.split("/")[-1],
                            )
            except Exception as e:
                yield DocumentContent(
                    content="",
                    metadata=self._create_metadata(
                        error=str(e),
                        github_owner=owner,
                        github_repo=repo,
                        github_path=current_path,
                    ),
                    source_id=f"{owner}/{repo}/{current_path}",
                    title=current_path.split("/")[-1] if current_path else repo,
                )

    async def load(self, source_id: str, **kwargs: Any) -> DocumentContent:
        """Load a single file from GitHub."""
        # source_id format: "owner/repo/path/to/file"
        parts = source_id.split("/", 2)
        if len(parts) != 3:
            raise ValueError(f"Invalid source_id format: {source_id}. Expected 'owner/repo/path'")

        owner, repo, file_path = parts
        ref = kwargs.get("ref")

        file_content = await self._fetch_file_content(owner, repo, file_path, ref)

        metadata = {
            "github_owner": owner,
            "github_repo": repo,
            "github_path": file_path,
            "github_ref": ref or "default",
        }

        return DocumentContent(
            content=file_content,
            metadata=self._create_metadata(**metadata),
            source_id=source_id,
            title=file_path.split("/")[-1],
        )

    async def load_many(self, source_ids: list[str], **kwargs: Any) -> AsyncIterator[DocumentContent]:
        """Load multiple files from GitHub."""
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
        """Validate GitHub file exists."""
        try:
            parts = source_id.split("/", 2)
            if len(parts) != 3:
                return False
            owner, repo, file_path = parts
            await self._fetch_file_content(owner, repo, file_path)
            return True
        except Exception:
            return False

    async def load_org_repos(self, org: str | None = None, **kwargs: Any) -> AsyncIterator[DocumentContent]:
        """Load all repositories from an organization."""
        org = org or self.org
        if not org:
            raise ValueError("Organization not specified")

        page = 1
        while True:
            response = await self.client.rest.repos.list_for_org(org, page=page, per_page=100)
            repos = response.parsed_data

            if not repos:
                break

            for repo in repos:
                if not repo.private or kwargs.get("include_private", False):
                    async for doc in self.load_repo(org, repo.name, **kwargs):
                        yield doc

            page += 1

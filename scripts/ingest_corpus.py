#!/usr/bin/env python
"""
ContextForge Corpus Ingestion CLI

Usage:
    python scripts/ingest_corpus.py <source_id> [options]

Examples:
    # Ingest a PDF file
    python scripts/ingest_corpus.py ./docs/manual.pdf --source-type pdf

    # Ingest a Markdown file
    python scripts/ingest_corpus.py ./docs/readme.md --source-type markdown

    # Ingest a Notion page
    python scripts/ingest_corpus.py <page_id> --source-type notion

    # Ingest a GitHub repo
    python scripts/ingest_corpus.py owner/repo/path --source-type github

    # Ingest with custom strategy and embedder
    python scripts/ingest_corpus.py ./docs/manual.pdf --strategy semantic --embedding-provider openai
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from contextforge.config import settings
from contextforge.ingestion import (
    IngestionPipeline,
    LoaderRegistry,
    ChunkerRegistry,
    EmbedderRegistry,
    IndexerRegistry,
)
from contextforge.storage.database import init_db


def parse_args() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="ContextForge Corpus Ingestion CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    parser.add_argument(
        "source_id",
        nargs="?",
        help="Source identifier (file path, page ID, repo path, channel ID)",
    )

    parser.add_argument(
        "--source-type",
        required=False,
        choices=LoaderRegistry.list_sources(),
        help="Source type",
    )

    parser.add_argument(
        "--strategy",
        choices=ChunkerRegistry.list_strategies(),
        default=settings.DEFAULT_CHUNK_STRATEGY,
        help=f"Chunking strategy (default: {settings.DEFAULT_CHUNK_STRATEGY})",
    )

    parser.add_argument(
        "--embedding-provider",
        choices=EmbedderRegistry.list_providers(),
        default="local",
        help="Embedding provider (default: local)",
    )

    parser.add_argument(
        "--vector-store",
        choices=IndexerRegistry.list_indexers(),
        default=settings.VECTOR_STORE,
        help=f"Vector store (default: {settings.VECTOR_STORE})",
    )

    parser.add_argument(
        "--metadata",
        type=json.loads,
        default="{}",
        help="Additional metadata as JSON string",
    )

    parser.add_argument(
        "--batch",
        type=str,
        help="Path to JSON file with batch of sources",
    )

    parser.add_argument(
        "--list-sources",
        action="store_true",
        help="List available source types and exit",
    )

    parser.add_argument(
        "--list-strategies",
        action="store_true",
        help="List available chunking strategies and exit",
    )

    parser.add_argument(
        "--list-providers",
        action="store_true",
        help="List available embedding providers and exit",
    )

    parser.add_argument(
        "--list-indexers",
        action="store_true",
        help="List available vector indexers and exit",
    )

    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Verbose output",
    )

    return parser.parse_args()


async def ingest_single(
    pipeline: IngestionPipeline,
    source_id: str,
    strategy: str | None,
    embedding_provider: str | None,
    metadata: dict[str, Any],
    verbose: bool,
) -> bool:
    """Ingest a single source."""
    try:
        if verbose:
            print(f"  Loading: {source_id}")

        result = await pipeline.ingest(
            source_id,
            strategy=strategy,
            embedding_provider=embedding_provider,
            metadata=metadata,
        )

        if result.success:
            print(f"✓ Success: {source_id}")
            print(f"  Document ID: {result.document_id}")
            print(f"  Chunks: {result.chunk_count}")
            print(f"  Strategy: {result.strategy}")
            print(f"  Embedder: {result.embedding_provider}/{result.embedding_model}")
        else:
            print(f"✗ Failed: {source_id}")
            print(f"  Error: {result.error_message}")

        return result.success

    except Exception as e:
        print(f"✗ Failed: {source_id}")
        print(f"  Error: {e}")
        return False


async def ingest_batch(
    pipeline: IngestionPipeline,
    batch_file: str,
    strategy: str | None,
    embedding_provider: str | None,
    metadata: dict[str, Any],
    verbose: bool,
) -> tuple[int, int]:
    """Ingest a batch of sources from JSON file."""
    with open(batch_file) as f:
        batch = json.load(f)

    if not isinstance(batch, list):
        raise ValueError("Batch file must contain a JSON array")

    success_count = 0
    total = len(batch)

    print(f"Processing {total} sources from {batch_file}...")

    for i, item in enumerate(batch, 1):
        if isinstance(item, str):
            source_id = item
            item_strategy = strategy
            item_provider = embedding_provider
            item_metadata = metadata
        elif isinstance(item, dict):
            source_id = item.get("source_id")
            item_strategy = item.get("strategy", strategy)
            item_provider = item.get("embedding_provider", embedding_provider)
            item_metadata = {**metadata, **item.get("metadata", {})}
        else:
            print(f"  [{i}/{total}] Invalid item format, skipping")
            continue

        if not source_id:
            print(f"  [{i}/{total}] Missing source_id, skipping")
            continue

        if verbose:
            print(f"  [{i}/{total}] ", end="")

        success = await ingest_single(
            pipeline, source_id, item_strategy, item_provider, item_metadata, verbose
        )
        if success:
            success_count += 1

    return success_count, total


async def main() -> int:
    """Main entry point."""
    args = parse_args()

    # Handle list commands
    if args.list_sources:
        print("Available source types:")
        for s in LoaderRegistry.list_sources():
            print(f"  {s}")
        return 0

    if args.list_strategies:
        print("Available chunking strategies:")
        for s in ChunkerRegistry.list_strategies():
            print(f"  {s}")
        return 0

    if args.list_providers:
        print("Available embedding providers:")
        for p in EmbedderRegistry.list_providers():
            print(f"  {p}")
        return 0

    if args.list_indexers:
        print("Available vector indexers:")
        for i in IndexerRegistry.list_indexers():
            print(f"  {i}")
        return 0

    # Validate required arguments
    if not args.source_id and not args.batch:
        print("Error: source_id or --batch is required")
        return 1

    if not args.source_type and args.source_id:
        # Try to infer from file extension
        path = Path(args.source_id)
        if path.suffix == ".pdf":
            args.source_type = "pdf"
        elif path.suffix in (".md", ".markdown", ".mdx"):
            args.source_type = "markdown"
        else:
            print("Error: --source-type is required")
            return 1

    # Initialize database
    print("Initializing database...")
    await init_db()

    # Create pipeline
    print(f"Creating pipeline: source={args.source_type}, strategy={args.strategy}, embedder={args.embedding_provider}, indexer={args.vector_store}")

    pipeline = IngestionPipeline.from_config(
        source_type=args.source_type,
        strategy=args.strategy,
        embedding_provider=args.embedding_provider,
        vector_store=args.vector_store,
    )

    await pipeline.initialize()

    try:
        if args.batch:
            success, total = await ingest_batch(
                pipeline,
                args.batch,
                args.strategy,
                args.embedding_provider,
                args.metadata,
                args.verbose,
            )
            print(f"\nCompleted: {success}/{total} successful")
            return 0 if success == total else 1
        else:
            success = await ingest_single(
                pipeline,
                args.source_id,
                args.strategy,
                args.embedding_provider,
                args.metadata,
                args.verbose,
            )
            return 0 if success else 1
    finally:
        await pipeline.close()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
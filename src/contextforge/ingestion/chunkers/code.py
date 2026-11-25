"""
ContextForge Code Chunker

Code-aware chunking using Tree-sitter for AST-based splitting.
"""

from __future__ import annotations

from typing import Any

from contextforge.ingestion.chunkers.base import BaseChunker, Chunk, ChunkerConfig, ChunkerRegistry
from contextforge.ingestion.chunkers.fixed import FixedChunker, FixedChunkerConfig

# Language mapping for tree-sitter
LANGUAGE_MAP = {
    ".py": "python",
    ".js": "javascript",
    ".jsx": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".java": "java",
    ".go": "go",
    ".rs": "rust",
    ".cpp": "cpp",
    ".cc": "cpp",
    ".cxx": "cpp",
    ".c": "c",
    ".h": "c",
    ".hpp": "cpp",
    ".cs": "c_sharp",
    ".php": "php",
    ".rb": "ruby",
    ".swift": "swift",
    ".kt": "kotlin",
    ".scala": "scala",
    ".clj": "clojure",
    ".fs": "fsharp",
    ".ml": "ocaml",
    ".ex": "elixir",
    ".exs": "elixir",
}


class CodeChunkerConfig(ChunkerConfig):
    """Configuration for code chunker."""

    max_lines: int = 100
    max_chars: int = 4000
    include_context_lines: int = 3  # Lines before/after to include
    fallback_to_fixed: bool = True


@ChunkerRegistry.register
class CodeChunker(BaseChunker):
    """Code-aware chunker using Tree-sitter."""

    strategy_name = "code"

    def __init__(self, config: CodeChunkerConfig | None = None):
        super().__init__(config or CodeChunkerConfig())
        self._parsers: dict[str, Any] = {}
        self._languages: dict[str, Any] = {}

    def _get_parser(self, language: str):
        """Get or create tree-sitter parser for language."""
        if language not in self._parsers:
            try:
                from tree_sitter import Parser
                from tree_sitter_language_pack import get_language

                # Try tree-sitter-language-pack first (newer, working API)
                try:
                    lang = get_language(language)
                    parser = Parser(lang)
                    self._languages[language] = lang
                    self._parsers[language] = parser
                except Exception:
                    # Fallback to tree-sitter-languages (older API)
                    try:
                        from tree_sitter_languages import get_parser as get_tsl_parser
                        parser = get_tsl_parser(language)
                        self._parsers[language] = parser
                    except Exception:
                        self._parsers[language] = None
            except Exception:
                self._parsers[language] = None
        return self._parsers.get(language)

    def _detect_language(self, file_path: str, content: str) -> str | None:
        """Detect programming language from file extension or content."""
        # Check file extension
        import os
        _, ext = os.path.splitext(file_path)
        if ext in LANGUAGE_MAP:
            return LANGUAGE_MAP[ext]

        # Check shebang
        if content.startswith("#!"):
            if "python" in content:
                return "python"
            elif "node" in content or "javascript" in content:
                return "javascript"
            elif "bash" in content or "sh" in content:
                return "bash"

        return None

    def _extract_nodes(self, parser, source_code: bytes, node_types: list[str]) -> list[dict[str, Any]]:
        """Extract AST nodes of specific types."""
        tree = parser.parse(source_code)
        root_node = tree.root_node

        nodes = []

        def traverse(node):
            if node.type in node_types:
                nodes.append({
                    "type": node.type,
                    "start_byte": node.start_byte,
                    "end_byte": node.end_byte,
                    "start_line": node.start_point[0],
                    "end_line": node.end_point[0],
                    "text": source_code[node.start_byte:node.end_byte].decode("utf-8", errors="replace"),
                })
            for child in node.children:
                traverse(child)

        traverse(root_node)
        return nodes

    def chunk(self, text: str, metadata: dict[str, Any] | None = None) -> list[Chunk]:
        """Chunk code using AST-based splitting."""
        if not text.strip():
            return []

        # Detect language
        file_path = metadata.get("file_path", "") if metadata else ""
        language = self._detect_language(file_path, text)

        if not language:
            # Fallback to fixed chunker
            if self.config.fallback_to_fixed:
                return self._fallback_chunk(text, metadata)
            return [Chunk(
                content=text,
                index=0,
                token_count=self._count_tokens(text),
                metadata=self._merge_metadata(metadata or {}, {"strategy": self.strategy_name}),
            )]

        parser = self._get_parser(language)
        if not parser:
            if self.config.fallback_to_fixed:
                return self._fallback_chunk(text, metadata)
            return [Chunk(
                content=text,
                index=0,
                token_count=self._count_tokens(text),
                metadata=self._merge_metadata(metadata or {}, {"strategy": self.strategy_name}),
            )]

        # Define node types to extract for each language
        node_types = self._get_node_types(language)

        # Extract code blocks
        source_bytes = text.encode("utf-8")
        nodes = self._extract_nodes(parser, source_bytes, node_types)

        if not nodes:
            if self.config.fallback_to_fixed:
                return self._fallback_chunk(text, metadata)
            return [Chunk(
                content=text,
                index=0,
                token_count=self._count_tokens(text),
                metadata=self._merge_metadata(metadata or {}, {"strategy": self.strategy_name}),
            )]

        # Create chunks from nodes
        chunks = []
        lines = text.split("\n")

        for i, node in enumerate(nodes):
            # Get context lines
            start_line = max(0, node["start_line"] - self.config.include_context_lines)
            end_line = min(len(lines), node["end_line"] + 1 + self.config.include_context_lines)

            chunk_lines = lines[start_line:end_line]
            chunk_text = "\n".join(chunk_lines)

            # Check size limits
            if len(chunk_text) > self.config.max_chars or len(chunk_lines) > self.config.max_lines:
                # Split large node
                sub_chunks = self._split_large_node(chunk_text, start_line, metadata, node)
                chunks.extend(sub_chunks)
            else:
                chunk_metadata = self._merge_metadata(metadata or {}, {
                    "strategy": self.strategy_name,
                    "language": language,
                    "node_type": node["type"],
                    "start_line": node["start_line"],
                    "end_line": node["end_line"],
                    "context_start_line": start_line,
                    "context_end_line": end_line - 1,
                })

                chunks.append(Chunk(
                    content=chunk_text,
                    index=len(chunks),
                    token_count=self._count_tokens(chunk_text),
                    metadata=chunk_metadata,
                ))

        # Handle code between nodes (imports, top-level statements)
        self._add_interstitial_chunks(nodes, lines, chunks, metadata, language)

        return chunks

    def _get_node_types(self, language: str) -> list[str]:
        """Get relevant AST node types for a language."""
        common_types = [
            "function_definition",
            "function_declaration",
            "method_definition",
            "class_definition",
            "class_declaration",
            "interface_declaration",
            "struct_definition",
            "enum_declaration",
            "type_declaration",
            "const_declaration",
            "variable_declaration",
            "import_declaration",
            "import_statement",
            "export_statement",
        ]

        language_specific = {
            "python": [
                "function_definition",
                "class_definition",
                "async_function_definition",
                "decorated_definition",
                "import_statement",
                "import_from_statement",
            ],
            "javascript": [
                "function_declaration",
                "function_expression",
                "arrow_function",
                "class_declaration",
                "class_expression",
                "method_definition",
                "import_statement",
                "export_statement",
                "variable_declaration",
            ],
            "typescript": [
                "function_declaration",
                "function_expression",
                "arrow_function",
                "class_declaration",
                "interface_declaration",
                "type_alias_declaration",
                "enum_declaration",
                "import_statement",
                "export_statement",
            ],
            "go": [
                "function_declaration",
                "method_declaration",
                "type_declaration",
                "const_declaration",
                "var_declaration",
                "import_declaration",
            ],
            "rust": [
                "function_item",
                "struct_item",
                "enum_item",
                "impl_item",
                "trait_item",
                "mod_item",
                "use_declaration",
                "const_item",
                "static_item",
            ],
            "java": [
                "method_declaration",
                "class_declaration",
                "interface_declaration",
                "enum_declaration",
                "field_declaration",
                "import_declaration",
            ],
            "c_sharp": [
                "method_declaration",
                "class_declaration",
                "interface_declaration",
                "struct_declaration",
                "enum_declaration",
                "property_declaration",
                "using_directive",
            ],
        }

        return language_specific.get(language, common_types)

    def _split_large_node(
        self,
        text: str,
        start_line: int,
        metadata: dict[str, Any] | None,
        node: dict[str, Any],
    ) -> list[Chunk]:
        """Split a large AST node into smaller chunks."""
        lines = text.split("\n")
        chunks = []

        for i in range(0, len(lines), self.config.max_lines):
            chunk_lines = lines[i:i + self.config.max_lines]
            chunk_text = "\n".join(chunk_lines)

            chunk_metadata = self._merge_metadata(metadata or {}, {
                "strategy": self.strategy_name,
                "language": metadata.get("language", "unknown") if metadata else "unknown",
                "node_type": node["type"],
                "part": f"{i // self.config.max_lines + 1}",
                "original_start_line": start_line + i,
                "original_end_line": min(start_line + i + len(chunk_lines), node["end_line"]),
            })

            chunks.append(Chunk(
                content=chunk_text,
                index=len(chunks),
                token_count=self._count_tokens(chunk_text),
                metadata=chunk_metadata,
            ))

        return chunks

    def _add_interstitial_chunks(
        self,
        nodes: list[dict[str, Any]],
        lines: list[str],
        chunks: list[Chunk],
        metadata: dict[str, Any] | None,
        language: str,
    ) -> None:
        """Add chunks for code between major nodes (imports, etc.)."""
        if not nodes:
            return

        # Sort nodes by start line
        nodes = sorted(nodes, key=lambda n: n["start_line"])

        # Check before first node
        first_start = nodes[0]["start_line"]
        if first_start > 0:
            interstitial_text = "\n".join(lines[:first_start])
            if interstitial_text.strip():
                chunks.append(Chunk(
                    content=interstitial_text,
                    index=len(chunks),
                    token_count=self._count_tokens(interstitial_text),
                    metadata=self._merge_metadata(metadata or {}, {
                        "strategy": self.strategy_name,
                        "language": language,
                        "node_type": "interstitial",
                        "section": "header",
                    }),
                ))

        # Check between nodes
        for i in range(len(nodes) - 1):
            gap_start = nodes[i]["end_line"] + 1
            gap_end = nodes[i + 1]["start_line"]
            if gap_end > gap_start:
                interstitial_text = "\n".join(lines[gap_start:gap_end])
                if interstitial_text.strip():
                    chunks.append(Chunk(
                        content=interstitial_text,
                        index=len(chunks),
                        token_count=self._count_tokens(interstitial_text),
                        metadata=self._merge_metadata(metadata or {}, {
                            "strategy": self.strategy_name,
                            "language": language,
                            "node_type": "interstitial",
                            "section": f"between_{i}",
                        }),
                    ))

        # Check after last node
        last_end = nodes[-1]["end_line"] + 1
        if last_end < len(lines):
            interstitial_text = "\n".join(lines[last_end:])
            if interstitial_text.strip():
                chunks.append(Chunk(
                    content=interstitial_text,
                    index=len(chunks),
                    token_count=self._count_tokens(interstitial_text),
                    metadata=self._merge_metadata(metadata or {}, {
                        "strategy": self.strategy_name,
                        "language": language,
                        "node_type": "interstitial",
                        "section": "footer",
                    }),
                ))

    def _fallback_chunk(self, text: str, metadata: dict[str, Any] | None) -> list[Chunk]:
        """Fallback to fixed chunking."""
        fixed_config = FixedChunkerConfig(
            chunk_size=self.config.chunk_size,
            chunk_overlap=self.config.chunk_overlap,
        )
        fixed_chunker = FixedChunker(fixed_config)
        chunks = fixed_chunker.chunk(text, metadata)
        for chunk in chunks:
            chunk.metadata["strategy"] = self.strategy_name
            chunk.metadata["fallback"] = "fixed"
        return chunks

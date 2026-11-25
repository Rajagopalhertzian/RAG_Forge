"""
Golden QA Dataset Management

Handles versioned golden QA pairs stored as JSONL with schema validation.
Supports loading, validation, and version management.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import jsonschema

# JSON Schema for golden QA pairs
GOLDEN_QA_SCHEMA = {
    "type": "object",
    "required": ["id", "question", "answer", "relevant_docs", "metadata"],
    "properties": {
        "id": {"type": "string", "format": "uuid"},
        "question": {"type": "string", "minLength": 1},
        "answer": {"type": "string", "minLength": 1},
        "relevant_docs": {
            "type": "array",
            "items": {"type": "string"},
            "minItems": 1,
        },
        "metadata": {
            "type": "object",
            "required": ["version", "created_at", "category", "difficulty"],
            "properties": {
                "version": {"type": "string", "pattern": "^v\\d+$"},
                "created_at": {"type": "string", "format": "date-time"},
                "category": {"type": "string"},
                "difficulty": {"type": "string", "enum": ["easy", "medium", "hard"]},
                "tags": {"type": "array", "items": {"type": "string"}},
                "source": {"type": "string"},
            },
            "additionalProperties": True,
        },
    },
    "additionalProperties": False,
}


@dataclass
class GoldenQA:
    """A single golden QA pair with metadata."""

    id: str
    question: str
    answer: str
    relevant_docs: list[str]
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if not self.id:
            self.id = str(uuid4())
        if "version" not in self.metadata:
            self.metadata["version"] = "v1"
        if "created_at" not in self.metadata:
            self.metadata["created_at"] = datetime.utcnow().isoformat() + "Z"

    def to_jsonl(self) -> str:
        """Serialize to JSONL line."""
        return json.dumps({
            "id": self.id,
            "question": self.question,
            "answer": self.answer,
            "relevant_docs": self.relevant_docs,
            "metadata": self.metadata,
        }, ensure_ascii=False)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> GoldenQA:
        """Create from dictionary."""
        return cls(
            id=data["id"],
            question=data["question"],
            answer=data["answer"],
            relevant_docs=data["relevant_docs"],
            metadata=data.get("metadata", {}),
        )

    def validate(self) -> tuple[bool, list[str]]:
        """Validate against schema."""
        try:
            jsonschema.validate(
                {
                    "id": self.id,
                    "question": self.question,
                    "answer": self.answer,
                    "relevant_docs": self.relevant_docs,
                    "metadata": self.metadata,
                },
                GOLDEN_QA_SCHEMA,
            )
            return True, []
        except jsonschema.ValidationError as e:
            return False, [str(e)]


class GoldenDataset:
    """Manages a collection of golden QA pairs."""

    def __init__(self, version: str = "v1"):
        self.version = version
        self.qa_pairs: list[GoldenQA] = []

    def add(self, qa: GoldenQA) -> None:
        """Add a QA pair."""
        if qa.metadata.get("version") != self.version:
            qa.metadata["version"] = self.version
        self.qa_pairs.append(qa)

    def add_batch(self, qa_list: list[GoldenQA]) -> None:
        """Add multiple QA pairs."""
        for qa in qa_list:
            self.add(qa)

    def remove(self, qa_id: str) -> bool:
        """Remove QA pair by ID."""
        for i, qa in enumerate(self.qa_pairs):
            if qa.id == qa_id:
                self.qa_pairs.pop(i)
                return True
        return False

    def get(self, qa_id: str) -> GoldenQA | None:
        """Get QA pair by ID."""
        for qa in self.qa_pairs:
            if qa.id == qa_id:
                return qa
        return None

    def filter_by_category(self, category: str) -> list[GoldenQA]:
        """Filter QA pairs by category."""
        return [qa for qa in self.qa_pairs if qa.metadata.get("category") == category]

    def filter_by_difficulty(self, difficulty: str) -> list[GoldenQA]:
        """Filter QA pairs by difficulty."""
        return [qa for qa in self.qa_pairs if qa.metadata.get("difficulty") == difficulty]

    def filter_by_tag(self, tag: str) -> list[GoldenQA]:
        """Filter QA pairs by tag."""
        return [qa for qa in self.qa_pairs if tag in qa.metadata.get("tags", [])]

    def to_jsonl(self, path: Path) -> None:
        """Save dataset to JSONL file."""
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            for qa in self.qa_pairs:
                f.write(qa.to_jsonl() + "\n")

    @classmethod
    def from_jsonl(cls, path: Path, version: str = None) -> GoldenDataset:
        """Load dataset from JSONL file."""
        dataset = cls(version=version or "v1")
        with open(path, encoding="utf-8") as f:
            for line_num, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                    qa = GoldenQA.from_dict(data)
                    # Validate
                    valid, errors = qa.validate()
                    if not valid:
                        raise ValueError(f"Line {line_num}: validation failed: {errors}")
                    dataset.qa_pairs.append(qa)
                except json.JSONDecodeError as e:
                    raise ValueError(f"Line {line_num}: invalid JSON: {e}")

        # Set version from first item if not provided
        if version is None and dataset.qa_pairs:
            dataset.version = dataset.qa_pairs[0].metadata.get("version", "v1")

        return dataset

    def validate_all(self) -> tuple[bool, list[str]]:
        """Validate all QA pairs in dataset."""
        errors = []
        for i, qa in enumerate(self.qa_pairs):
            valid, qa_errors = qa.validate()
            if not valid:
                errors.extend([f"QA {i} ({qa.id}): {e}" for e in qa_errors])
        return len(errors) == 0, errors

    def stats(self) -> dict[str, Any]:
        """Get dataset statistics."""
        if not self.qa_pairs:
            return {"count": 0, "version": self.version}

        categories = {}
        difficulties = {}
        tags = {}

        for qa in self.qa_pairs:
            cat = qa.metadata.get("category", "unknown")
            categories[cat] = categories.get(cat, 0) + 1

            diff = qa.metadata.get("difficulty", "unknown")
            difficulties[diff] = difficulties.get(diff, 0) + 1

            for tag in qa.metadata.get("tags", []):
                tags[tag] = tags.get(tag, 0) + 1

        return {
            "count": len(self.qa_pairs),
            "version": self.version,
            "categories": categories,
            "difficulties": difficulties,
            "tags": tags,
            "avg_relevant_docs": sum(len(qa.relevant_docs) for qa in self.qa_pairs) / len(self.qa_pairs),
        }

    def __len__(self) -> int:
        return len(self.qa_pairs)

    def __iter__(self):
        return iter(self.qa_pairs)


def load_golden_set(version: str, base_path: Path = None) -> GoldenDataset:
    """
    Load a golden QA dataset by version.

    Args:
        version: Version string (e.g., "v1", "v2")
        base_path: Base directory for golden sets (default: tests/evaluation/golden_sets)

    Returns:
        GoldenDataset instance
    """
    if base_path is None:
        base_path = Path("tests/evaluation/golden_sets")

    file_path = base_path / f"{version}_baseline.jsonl"
    if not file_path.exists():
        # Try alternative naming
        file_path = base_path / f"{version}_expanded.jsonl"

    if not file_path.exists():
        raise FileNotFoundError(f"Golden set not found: {file_path}")

    return GoldenDataset.from_jsonl(file_path, version=version)


def list_available_versions(base_path: Path = None) -> list[str]:
    """List available golden set versions."""
    if base_path is None:
        base_path = Path("tests/evaluation/golden_sets")

    versions = set()
    for file_path in base_path.glob("*.jsonl"):
        # Extract version from filename
        stem = file_path.stem
        if stem.endswith("_baseline") or stem.endswith("_expanded"):
            version = stem.replace("_baseline", "").replace("_expanded", "")
            versions.add(version)

    return sorted(versions)

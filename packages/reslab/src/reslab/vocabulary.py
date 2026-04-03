"""Controlled vocabulary for domain tags.

Normalizes ad-hoc domain tags to a canonical set, resolves aliases to
canonical tags, and suggests nearest matches for unknown tags.
"""

from __future__ import annotations

import difflib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Sequence

VOCAB_FILENAME = "vocabulary.json"


@dataclass
class Vocabulary:
    """Controlled vocabulary mapping aliases and subtags to canonical domain tags.

    *Aliases* are true synonyms — the original tag disappears and is replaced
    by canonical tag(s).  *Subtags* are hierarchical — the original tag is
    preserved and its parent canonical tag(s) are added alongside it.
    """

    tags: dict[str, str]  # canonical_tag -> description
    aliases: dict[str, list[str]]  # alias -> list of canonical tags it expands to
    subtags: dict[str, list[str]] = field(default_factory=dict)  # subtag -> parent canonical tags

    def normalize(self, domains: Sequence[str]) -> tuple[list[str], list[tuple[str, list[str]]]]:
        """Normalize domain tags through vocabulary.

        Returns (normalized_tags, warnings) where warnings is a list of
        (unknown_tag, suggestions) tuples.

        Aliases replace the original tag with canonical tag(s).
        Subtags preserve the original tag and add parent canonical tag(s).
        """
        result: list[str] = []
        warnings: list[tuple[str, list[str]]] = []

        for tag in domains:
            if tag in self.tags:
                if tag not in result:
                    result.append(tag)
            elif tag in self.aliases:
                for canonical in self.aliases[tag]:
                    if canonical not in result:
                        result.append(canonical)
            elif tag in self.subtags:
                # Subtag: preserve original AND add parent(s)
                if tag not in result:
                    result.append(tag)
                for parent in self.subtags[tag]:
                    if parent not in result:
                        result.append(parent)
            else:
                all_known = (
                    list(self.tags.keys())
                    + list(self.aliases.keys())
                    + list(self.subtags.keys())
                )
                matches = difflib.get_close_matches(tag, all_known, n=3, cutoff=0.4)
                warnings.append((tag, matches))
                if tag not in result:
                    result.append(tag)

        return sorted(result), warnings

    def canonical_tags(self) -> list[str]:
        """Return sorted list of canonical tag names."""
        return sorted(self.tags.keys())

    def to_dict(self) -> dict:
        d: dict = {
            "tags": self.tags,
            "aliases": self.aliases,
        }
        if self.subtags:
            d["subtags"] = self.subtags
        return d

    @classmethod
    def from_dict(cls, data: dict) -> Vocabulary:
        return cls(
            tags=data.get("tags", {}),
            aliases=data.get("aliases", {}),
            subtags=data.get("subtags", {}),
        )


def load_vocabulary(store_path: str | Path) -> Vocabulary | None:
    """Load vocabulary from store. Returns None if no vocabulary config exists."""
    vocab_path = Path(store_path) / VOCAB_FILENAME
    if not vocab_path.exists():
        return None
    with open(vocab_path) as f:
        return Vocabulary.from_dict(json.load(f))


def save_vocabulary(vocab: Vocabulary, store_path: str | Path) -> None:
    """Save vocabulary config to store."""
    store_dir = Path(store_path)
    store_dir.mkdir(parents=True, exist_ok=True)
    vocab_path = store_dir / VOCAB_FILENAME
    with open(vocab_path, "w") as f:
        json.dump(vocab.to_dict(), f, indent=2, sort_keys=True)


def default_vocabulary() -> Vocabulary:
    """Create a default vocabulary suitable for ML research."""
    return Vocabulary(
        tags={
            "training": "Model training, optimization, and convergence",
            "inference": "Model inference, generation, and deployment",
            "architecture": "Model architecture and design choices",
            "data": "Datasets, preprocessing, and data pipeline",
            "evaluation": "Metrics, benchmarks, and model evaluation",
            "grokking": "Grokking, delayed generalization, and phase transitions",
            "verification": "Formal verification and proof checking",
            "lean": "Lean theorem prover and formalization",
            "replication": "Reproducibility and replication methodology",
            "tooling": "Developer tools, CLI, and infrastructure",
            "theory": "Theoretical analysis and mathematical foundations",
            "scaling": "Scaling laws, compute efficiency, and model size",
        },
        aliases={
            # True synonyms — original disappears, replaced by canonical
            "lean-verification": ["lean", "verification"],
            "lean-traces": ["lean", "training"],
            "lean-proofs": ["lean", "verification"],
            "model-training": ["training"],
            "fine-tuning": ["training"],
            "finetuning": ["training"],
            "model-architecture": ["architecture"],
            "dataset": ["data"],
            "datasets": ["data"],
            "benchmark": ["evaluation"],
            "benchmarks": ["evaluation"],
            "metrics": ["evaluation"],
            "reproduce": ["replication"],
            "reproducibility": ["replication"],
            "infra": ["tooling"],
            "infrastructure": ["tooling"],
            "math": ["theory"],
            "scale": ["scaling"],
            "compute": ["scaling"],
        },
        subtags={
            # Hierarchical subtags — original preserved, parent added
            "pantograph": ["lean"],
            "mathlib": ["lean"],
            "lora": ["training"],
            "rlhf": ["training"],
            "distillation": ["training"],
            "transformer": ["architecture"],
            "tokenization": ["data"],
            "chinchilla": ["scaling"],
        },
    )

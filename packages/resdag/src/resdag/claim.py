"""Claim data structure and serialization."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from multiformats import CID, multihash


class ClaimType(str, Enum):
    """Types of claims in the ResDAG protocol."""

    RESULT = "result"
    METHOD = "method"
    HYPOTHESIS = "hypothesis"
    REPLICATION = "replication"
    EQUIVALENCE = "equivalence"
    REFUTATION = "refutation"
    SUPERSESSION = "supersession"
    VERIFICATION = "verification"


def _utcnow() -> str:
    """Return current UTC time as ISO 8601 string with Z suffix."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass(frozen=True)
class Claim:
    """A single research claim — the atomic unit of the ResDAG protocol.

    Claims are immutable and content-addressed. The CID is derived from the
    canonical JSON serialization of all fields except signature.
    """

    claim: str
    type: ClaimType
    parents: tuple[str, ...] = ()
    evidence: tuple[str, ...] = ()
    domain: tuple[str, ...] = ()
    author: str = ""
    timestamp: str = field(default_factory=_utcnow)
    signature: str = ""

    def __post_init__(self) -> None:
        # Coerce type from string if needed
        if isinstance(self.type, str):
            object.__setattr__(self, "type", ClaimType(self.type))
        # Coerce lists to tuples for hashability
        for attr in ("parents", "evidence", "domain"):
            val = getattr(self, attr)
            if isinstance(val, list):
                object.__setattr__(self, attr, tuple(val))

    def canonical_dict(self) -> dict:
        """Return the canonical dictionary for hashing (excludes signature)."""
        return {
            "author": self.author,
            "claim": self.claim,
            "domain": list(self.domain),
            "evidence": list(self.evidence),
            "parents": list(self.parents),
            "timestamp": self.timestamp,
            "type": self.type.value,
        }

    def canonical_bytes(self) -> bytes:
        """Return deterministic JSON bytes for CID computation.

        Uses sorted keys and no whitespace for canonical form.
        """
        return json.dumps(
            self.canonical_dict(), sort_keys=True, separators=(",", ":")
        ).encode("utf-8")

    def cid(self) -> str:
        """Compute the content identifier (CID) for this claim.

        Uses CIDv1 with json codec and SHA-256 hash. The json codec
        distinguishes claim CIDs from evidence CIDs (which use raw codec),
        making the object type self-describing from the CID alone.
        """
        digest = multihash.digest(self.canonical_bytes(), "sha2-256")
        return str(CID("base32", 1, "json", digest))

    def to_dict(self) -> dict:
        """Serialize to a full dictionary (includes signature)."""
        d = self.canonical_dict()
        d["signature"] = self.signature
        return d

    def to_json(self) -> str:
        """Serialize to JSON string (human-readable, includes signature)."""
        return json.dumps(self.to_dict(), sort_keys=True, indent=2)

    @classmethod
    def from_dict(cls, data: dict) -> Claim:
        """Deserialize from a dictionary."""
        return cls(
            claim=data["claim"],
            type=ClaimType(data["type"]),
            parents=tuple(data.get("parents", [])),
            evidence=tuple(data.get("evidence", [])),
            domain=tuple(data.get("domain", [])),
            author=data.get("author", ""),
            timestamp=data.get("timestamp", ""),
            signature=data.get("signature", ""),
        )

    @classmethod
    def from_json(cls, json_str: str) -> Claim:
        """Deserialize from a JSON string."""
        return cls.from_dict(json.loads(json_str))

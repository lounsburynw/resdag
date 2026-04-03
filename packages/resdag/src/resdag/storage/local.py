"""Local filesystem storage (content-addressed)."""

from __future__ import annotations

import json
from pathlib import Path

from resdag.claim import Claim
from resdag.evidence import compute_cid as _evidence_cid


class LocalStore:
    """Content-addressed local storage for claims.

    Objects stored at objects/{cid[:2]}/{cid[2:]} following
    git's object directory convention.
    """

    def __init__(self, root: Path | str) -> None:
        self.root = Path(root)
        self.objects_dir = self.root / "objects"
        self.evidence_dir = self.root / "evidence"

    def init(self) -> None:
        """Initialize the storage directory structure."""
        self.objects_dir.mkdir(parents=True, exist_ok=True)
        self.evidence_dir.mkdir(parents=True, exist_ok=True)

    def _object_path(self, cid: str) -> Path:
        return self.objects_dir / cid[:2] / cid[2:]

    def put(self, claim: Claim) -> str:
        """Store a claim, returning its CID. Duplicate writes are no-ops."""
        cid = claim.cid()
        path = self._object_path(cid)
        if path.exists():
            return cid
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(claim.to_json(), encoding="utf-8")
        return cid

    def get(self, cid: str) -> Claim:
        """Retrieve a claim by CID. Raises KeyError if not found."""
        path = self._object_path(cid)
        if not path.exists():
            raise KeyError(cid)
        claim = Claim.from_json(path.read_text(encoding="utf-8"))
        if claim.cid() != cid:
            raise ValueError(
                f"Integrity error: stored content does not match CID {cid}"
            )
        return claim

    def has(self, cid: str) -> bool:
        """Check if a CID exists in the store."""
        return self._object_path(cid).exists()

    def list_cids(self) -> list[str]:
        """List all CIDs in the store."""
        cids = []
        if not self.objects_dir.exists():
            return cids
        for prefix_dir in sorted(self.objects_dir.iterdir()):
            if prefix_dir.is_dir() and len(prefix_dir.name) == 2:
                for obj_file in sorted(prefix_dir.iterdir()):
                    if obj_file.is_file():
                        cids.append(prefix_dir.name + obj_file.name)
        return cids

    # ── Evidence storage ──────────────────────────────────────────

    def _evidence_path(self, cid: str) -> Path:
        return self.evidence_dir / cid[:2] / cid[2:]

    def put_evidence(self, data: bytes, filename: str = "", media_type: str = "") -> str:
        """Store evidence bytes, returning CID.

        Content writes are idempotent (same bytes = same CID, no re-write).
        Metadata sidecar is always updated to reflect the latest filename
        and media_type, since metadata is advisory (not content-addressed).
        """
        cid = _evidence_cid(data)
        path = self._evidence_path(cid)
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        meta = {"filename": filename, "media_type": media_type, "size": len(data)}
        Path(str(path) + ".meta").write_text(
            json.dumps(meta, sort_keys=True, indent=2), encoding="utf-8"
        )
        return cid

    def get_evidence(self, cid: str) -> bytes:
        """Retrieve evidence bytes by CID. Raises KeyError if not found."""
        path = self._evidence_path(cid)
        if not path.exists():
            raise KeyError(cid)
        data = path.read_bytes()
        if _evidence_cid(data) != cid:
            raise ValueError(
                f"Integrity error: stored evidence does not match CID {cid}"
            )
        return data

    def get_evidence_meta(self, cid: str) -> dict:
        """Retrieve evidence metadata by CID. Returns empty dict if no metadata."""
        meta_path = Path(str(self._evidence_path(cid)) + ".meta")
        if not meta_path.exists():
            return {}
        return json.loads(meta_path.read_text(encoding="utf-8"))

    def has_evidence(self, cid: str) -> bool:
        """Check if evidence with this CID exists."""
        return self._evidence_path(cid).exists()

    def list_evidence_cids(self) -> list[str]:
        """List all evidence CIDs in the store."""
        cids = []
        if not self.evidence_dir.exists():
            return cids
        for prefix_dir in sorted(self.evidence_dir.iterdir()):
            if prefix_dir.is_dir() and len(prefix_dir.name) == 2:
                for obj_file in sorted(prefix_dir.iterdir()):
                    if obj_file.is_file() and not obj_file.name.endswith(".meta"):
                        cids.append(prefix_dir.name + obj_file.name)
        return cids

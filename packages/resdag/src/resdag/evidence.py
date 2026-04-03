"""Evidence artifact handling.

Evidence artifacts are arbitrary files (data, code, images) stored as
content-addressed objects. Each artifact is identified by a CID computed
from its raw bytes using CIDv1 with the raw codec and SHA-256 hash.
Claims use the json codec to make object type self-describing from the CID.
"""

from __future__ import annotations

from multiformats import CID, multihash


def compute_cid(data: bytes) -> str:
    """Compute a content identifier for raw evidence bytes.

    Uses CIDv1 with raw codec and SHA-256 hash. Claims use the json
    codec instead, so object type is distinguishable from the CID alone.
    """
    digest = multihash.digest(data, "sha2-256")
    return str(CID("base32", 1, "raw", digest))

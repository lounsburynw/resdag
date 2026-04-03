"""DID-based author identity.

Generates Ed25519 keypairs, derives did:key identifiers, signs claims,
and verifies signatures. Identity is portable via raw key serialization.
"""

from __future__ import annotations

import base64

from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PrivateFormat,
    PublicFormat,
)
from multiformats import multibase

from resdag.claim import Claim

# Ed25519 multicodec prefix (varint-encoded 0xed)
_ED25519_MULTICODEC = b"\xed\x01"


class Identity:
    """A DID-based author identity backed by an Ed25519 keypair."""

    def __init__(self, private_key: Ed25519PrivateKey) -> None:
        self._private_key = private_key
        self._public_key = private_key.public_key()

    @classmethod
    def generate(cls) -> Identity:
        """Generate a new random identity."""
        return cls(Ed25519PrivateKey.generate())

    @property
    def did(self) -> str:
        """Return the did:key identifier for this identity.

        Format: did:key:<multibase-base58btc(multicodec-ed25519-pub ++ raw-pub-key)>
        """
        raw_pub = self._public_key.public_bytes(Encoding.Raw, PublicFormat.Raw)
        encoded = multibase.encode(_ED25519_MULTICODEC + raw_pub, "base58btc")
        return f"did:key:{encoded}"

    def sign(self, claim: Claim) -> Claim:
        """Sign a claim, returning a new Claim with author and signature set.

        The signature covers the claim's canonical bytes (which exclude the
        signature field). The author is set to this identity's DID.
        """
        authored = Claim(
            claim=claim.claim,
            type=claim.type,
            parents=claim.parents,
            evidence=claim.evidence,
            domain=claim.domain,
            author=self.did,
            timestamp=claim.timestamp,
        )
        sig_bytes = self._private_key.sign(authored.canonical_bytes())
        sig_str = base64.urlsafe_b64encode(sig_bytes).decode("ascii").rstrip("=")
        return Claim(
            claim=authored.claim,
            type=authored.type,
            parents=authored.parents,
            evidence=authored.evidence,
            domain=authored.domain,
            author=authored.author,
            timestamp=authored.timestamp,
            signature=sig_str,
        )

    def to_bytes(self) -> bytes:
        """Serialize the private key as raw 32-byte seed.

        Portable across devices — import with Identity.from_bytes().
        """
        return self._private_key.private_bytes(
            Encoding.Raw, PrivateFormat.Raw, NoEncryption()
        )

    @classmethod
    def from_bytes(cls, data: bytes) -> Identity:
        """Deserialize an identity from raw private key bytes."""
        return cls(Ed25519PrivateKey.from_private_bytes(data))


def _decode_did_key(did: str) -> Ed25519PublicKey:
    """Extract an Ed25519 public key from a did:key string."""
    encoded = did[len("did:key:"):]
    decoded = multibase.decode(encoded)
    if not decoded.startswith(_ED25519_MULTICODEC):
        raise ValueError(f"Not an Ed25519 did:key: {did}")
    raw_pub = decoded[len(_ED25519_MULTICODEC):]
    return Ed25519PublicKey.from_public_bytes(raw_pub)


def _decode_signature(sig_str: str) -> bytes:
    """Decode a base64url (no-padding) signature string."""
    padding = 4 - len(sig_str) % 4
    if padding != 4:
        sig_str += "=" * padding
    return base64.urlsafe_b64decode(sig_str)


def verify(claim: Claim) -> bool:
    """Verify a claim's signature against its author DID.

    Returns True if the signature is valid. Returns False if the author
    is not a did:key, the signature is missing, or verification fails.
    """
    if not claim.author.startswith("did:key:"):
        return False
    if not claim.signature:
        return False
    try:
        pub_key = _decode_did_key(claim.author)
        sig_bytes = _decode_signature(claim.signature)
        pub_key.verify(sig_bytes, claim.canonical_bytes())
        return True
    except Exception:
        return False

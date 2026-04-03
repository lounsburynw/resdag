"""Tests for DID-based author identity."""

import pytest

from resdag.claim import Claim, ClaimType
from resdag.identity import Identity, verify


# ── Generation ────────────────────────────────────────────────────────


class TestGeneration:
    def test_generate_creates_identity(self):
        ident = Identity.generate()
        assert ident is not None

    def test_did_starts_with_did_key_z(self):
        ident = Identity.generate()
        assert ident.did.startswith("did:key:z")

    def test_did_is_stable(self):
        ident = Identity.generate()
        assert ident.did == ident.did

    def test_two_identities_have_different_dids(self):
        id1 = Identity.generate()
        id2 = Identity.generate()
        assert id1.did != id2.did

    def test_did_has_expected_length(self):
        # did:key:z + base58btc(2-byte prefix + 32-byte key) ≈ 56 chars
        ident = Identity.generate()
        assert len(ident.did) > 50


# ── Signing ───────────────────────────────────────────────────────────


class TestSigning:
    def test_sign_sets_author(self):
        ident = Identity.generate()
        claim = Claim(claim="water boils at 100C", type=ClaimType.RESULT)
        signed = ident.sign(claim)
        assert signed.author == ident.did

    def test_sign_sets_signature(self):
        ident = Identity.generate()
        claim = Claim(claim="water boils at 100C", type=ClaimType.RESULT)
        signed = ident.sign(claim)
        assert signed.signature != ""

    def test_sign_preserves_claim_content(self):
        ident = Identity.generate()
        claim = Claim(
            claim="water boils at 100C",
            type=ClaimType.RESULT,
            domain=("chemistry", "thermodynamics"),
            evidence=("bafkreibrl",),
        )
        signed = ident.sign(claim)
        assert signed.claim == claim.claim
        assert signed.type == claim.type
        assert signed.domain == claim.domain
        assert signed.evidence == claim.evidence
        assert signed.timestamp == claim.timestamp

    def test_sign_returns_new_claim(self):
        ident = Identity.generate()
        claim = Claim(claim="test", type=ClaimType.RESULT)
        signed = ident.sign(claim)
        assert signed is not claim

    def test_signed_claim_has_valid_cid(self):
        ident = Identity.generate()
        claim = Claim(claim="test", type=ClaimType.RESULT)
        signed = ident.sign(claim)
        cid = signed.cid()
        assert cid.startswith("bagaaiera")

    def test_signing_is_deterministic(self):
        """Ed25519 signatures are deterministic — same key + same content = same sig."""
        ident = Identity.generate()
        claim = Claim(claim="test", type=ClaimType.RESULT)
        sig1 = ident.sign(claim).signature
        sig2 = ident.sign(claim).signature
        assert sig1 == sig2

    def test_sign_overwrites_existing_author(self):
        ident = Identity.generate()
        claim = Claim(claim="test", type=ClaimType.RESULT, author="did:web:old")
        signed = ident.sign(claim)
        assert signed.author == ident.did


# ── Verification ──────────────────────────────────────────────────────


class TestVerification:
    def test_verify_valid_signature(self):
        ident = Identity.generate()
        claim = Claim(claim="water boils at 100C", type=ClaimType.RESULT)
        signed = ident.sign(claim)
        assert verify(signed) is True

    def test_tampered_claim_text_fails(self):
        ident = Identity.generate()
        signed = ident.sign(Claim(claim="water boils at 100C", type=ClaimType.RESULT))
        tampered = Claim(
            claim="water boils at 50C",
            type=signed.type,
            parents=signed.parents,
            evidence=signed.evidence,
            domain=signed.domain,
            author=signed.author,
            timestamp=signed.timestamp,
            signature=signed.signature,
        )
        assert verify(tampered) is False

    def test_tampered_type_fails(self):
        ident = Identity.generate()
        signed = ident.sign(Claim(claim="test", type=ClaimType.RESULT))
        tampered = Claim(
            claim=signed.claim,
            type=ClaimType.HYPOTHESIS,
            author=signed.author,
            timestamp=signed.timestamp,
            signature=signed.signature,
        )
        assert verify(tampered) is False

    def test_tampered_domain_fails(self):
        ident = Identity.generate()
        signed = ident.sign(
            Claim(claim="test", type=ClaimType.RESULT, domain=("physics",))
        )
        tampered = Claim(
            claim=signed.claim,
            type=signed.type,
            domain=("chemistry",),
            author=signed.author,
            timestamp=signed.timestamp,
            signature=signed.signature,
        )
        assert verify(tampered) is False

    def test_tampered_author_fails(self):
        id1 = Identity.generate()
        id2 = Identity.generate()
        signed = id1.sign(Claim(claim="test", type=ClaimType.RESULT))
        tampered = Claim(
            claim=signed.claim,
            type=signed.type,
            author=id2.did,
            timestamp=signed.timestamp,
            signature=signed.signature,
        )
        assert verify(tampered) is False

    def test_tampered_timestamp_fails(self):
        ident = Identity.generate()
        signed = ident.sign(Claim(claim="test", type=ClaimType.RESULT))
        tampered = Claim(
            claim=signed.claim,
            type=signed.type,
            author=signed.author,
            timestamp="2000-01-01T00:00:00Z",
            signature=signed.signature,
        )
        assert verify(tampered) is False

    def test_no_signature_returns_false(self):
        ident = Identity.generate()
        claim = Claim(claim="test", type=ClaimType.RESULT, author=ident.did)
        assert verify(claim) is False

    def test_no_author_returns_false(self):
        assert verify(Claim(claim="test", type=ClaimType.RESULT, signature="abc")) is False

    def test_non_did_key_author_returns_false(self):
        claim = Claim(
            claim="test", type=ClaimType.RESULT,
            author="did:web:example.com", signature="abc",
        )
        assert verify(claim) is False

    def test_garbage_signature_returns_false(self):
        ident = Identity.generate()
        claim = Claim(
            claim="test", type=ClaimType.RESULT,
            author=ident.did, signature="not-a-real-signature",
        )
        assert verify(claim) is False

    def test_wrong_key_signature_fails(self):
        """Signature from one identity doesn't verify under another's DID."""
        id1 = Identity.generate()
        id2 = Identity.generate()
        signed_by_1 = id1.sign(Claim(claim="test", type=ClaimType.RESULT))
        signed_by_2 = id2.sign(Claim(claim="test", type=ClaimType.RESULT))
        # Swap: id1's author + id2's signature
        franken = Claim(
            claim="test", type=ClaimType.RESULT,
            author=signed_by_1.author,
            timestamp=signed_by_1.timestamp,
            signature=signed_by_2.signature,
        )
        assert verify(franken) is False


# ── Portability ───────────────────────────────────────────────────────


class TestPortability:
    def test_to_bytes_is_32_bytes(self):
        ident = Identity.generate()
        assert len(ident.to_bytes()) == 32

    def test_roundtrip_preserves_did(self):
        ident = Identity.generate()
        restored = Identity.from_bytes(ident.to_bytes())
        assert restored.did == ident.did

    def test_restored_identity_can_sign_and_verify(self):
        ident = Identity.generate()
        restored = Identity.from_bytes(ident.to_bytes())
        claim = Claim(claim="test", type=ClaimType.RESULT)
        signed = restored.sign(claim)
        assert verify(signed) is True

    def test_restored_signatures_match_original(self):
        """Same key bytes → same signatures (Ed25519 is deterministic)."""
        ident = Identity.generate()
        restored = Identity.from_bytes(ident.to_bytes())
        claim = Claim(claim="test", type=ClaimType.RESULT)
        assert ident.sign(claim).signature == restored.sign(claim).signature

    def test_invalid_bytes_raises(self):
        with pytest.raises(Exception):
            Identity.from_bytes(b"too short")

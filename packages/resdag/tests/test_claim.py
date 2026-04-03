"""Tests for claim data structure, serialization, and CID generation."""

import json

import pytest

from resdag.claim import Claim, ClaimType


@pytest.fixture
def sample_claim():
    """A minimal claim for testing."""
    return Claim(
        claim="Grokking occurs after 10x the interpolation threshold",
        type=ClaimType.RESULT,
        parents=("bafkrei_parent1",),
        evidence=("bafkrei_evidence1", "bafkrei_evidence2"),
        domain=("ml.generalization", "ml.grokking"),
        author="did:key:z6MkhaXgBZDvotDkL5257faiztiGiC2QtKLGpbnnEGta2doK",
        timestamp="2026-04-02T12:00:00Z",
    )


class TestClaimType:
    def test_all_types_exist(self):
        expected = {"result", "method", "hypothesis", "replication", "equivalence", "refutation", "verification"}
        assert {t.value for t in ClaimType} == expected

    def test_string_coercion(self):
        assert ClaimType("result") == ClaimType.RESULT
        assert ClaimType("refutation") == ClaimType.REFUTATION

    def test_invalid_type_raises(self):
        with pytest.raises(ValueError):
            ClaimType("invalid_type")


class TestClaimCreation:
    def test_minimal_claim(self):
        c = Claim(claim="Water boils at 100C at 1atm", type=ClaimType.RESULT)
        assert c.claim == "Water boils at 100C at 1atm"
        assert c.type == ClaimType.RESULT
        assert c.parents == ()
        assert c.evidence == ()
        assert c.domain == ()
        assert c.author == ""
        assert c.timestamp  # auto-generated
        assert c.signature == ""

    def test_full_claim(self, sample_claim):
        assert sample_claim.claim == "Grokking occurs after 10x the interpolation threshold"
        assert sample_claim.type == ClaimType.RESULT
        assert sample_claim.parents == ("bafkrei_parent1",)
        assert len(sample_claim.evidence) == 2
        assert sample_claim.domain == ("ml.generalization", "ml.grokking")
        assert sample_claim.author.startswith("did:key:")
        assert sample_claim.timestamp == "2026-04-02T12:00:00Z"

    def test_type_from_string(self):
        c = Claim(claim="test", type="hypothesis")
        assert c.type == ClaimType.HYPOTHESIS

    def test_lists_coerced_to_tuples(self):
        c = Claim(
            claim="test",
            type=ClaimType.RESULT,
            parents=["a", "b"],
            evidence=["c"],
            domain=["d.e"],
        )
        assert isinstance(c.parents, tuple)
        assert isinstance(c.evidence, tuple)
        assert isinstance(c.domain, tuple)

    def test_immutable(self, sample_claim):
        with pytest.raises(AttributeError):
            sample_claim.claim = "modified"


class TestSerialization:
    def test_to_dict(self, sample_claim):
        d = sample_claim.to_dict()
        assert d["claim"] == sample_claim.claim
        assert d["type"] == "result"
        assert d["parents"] == ["bafkrei_parent1"]
        assert d["evidence"] == ["bafkrei_evidence1", "bafkrei_evidence2"]
        assert d["domain"] == ["ml.generalization", "ml.grokking"]
        assert d["author"] == sample_claim.author
        assert d["timestamp"] == "2026-04-02T12:00:00Z"
        assert d["signature"] == ""

    def test_to_json_is_valid(self, sample_claim):
        j = sample_claim.to_json()
        parsed = json.loads(j)
        assert parsed["claim"] == sample_claim.claim

    def test_round_trip_dict(self, sample_claim):
        d = sample_claim.to_dict()
        restored = Claim.from_dict(d)
        assert restored.claim == sample_claim.claim
        assert restored.type == sample_claim.type
        assert restored.parents == sample_claim.parents
        assert restored.evidence == sample_claim.evidence
        assert restored.domain == sample_claim.domain
        assert restored.author == sample_claim.author
        assert restored.timestamp == sample_claim.timestamp
        assert restored.signature == sample_claim.signature

    def test_round_trip_json(self, sample_claim):
        j = sample_claim.to_json()
        restored = Claim.from_json(j)
        assert restored == sample_claim

    def test_round_trip_preserves_cid(self, sample_claim):
        """CID must survive a serialize → deserialize round trip."""
        original_cid = sample_claim.cid()
        restored = Claim.from_json(sample_claim.to_json())
        assert restored.cid() == original_cid


class TestCID:
    def test_cid_is_string(self, sample_claim):
        cid = sample_claim.cid()
        assert isinstance(cid, str)
        assert cid.startswith("bagaaiera")  # base32 CIDv1 with json codec

    def test_cid_deterministic(self, sample_claim):
        """Same claim always produces the same CID."""
        assert sample_claim.cid() == sample_claim.cid()

    def test_identical_claims_same_cid(self):
        """Two independently constructed identical claims produce the same CID."""
        kwargs = dict(
            claim="Increased CO2 correlates with higher surface temperature",
            type=ClaimType.RESULT,
            parents=(),
            evidence=(),
            domain=("climate.atmospheric_science",),
            author="did:key:z6MkTest",
            timestamp="2026-01-01T00:00:00Z",
        )
        c1 = Claim(**kwargs)
        c2 = Claim(**kwargs)
        assert c1.cid() == c2.cid()

    def test_different_claim_text_different_cid(self, sample_claim):
        other = Claim(
            claim="Different claim text",
            type=sample_claim.type,
            parents=sample_claim.parents,
            evidence=sample_claim.evidence,
            domain=sample_claim.domain,
            author=sample_claim.author,
            timestamp=sample_claim.timestamp,
        )
        assert other.cid() != sample_claim.cid()

    def test_different_type_different_cid(self):
        kwargs = dict(
            claim="Same text",
            parents=(),
            evidence=(),
            domain=(),
            author="",
            timestamp="2026-01-01T00:00:00Z",
        )
        c1 = Claim(type=ClaimType.RESULT, **kwargs)
        c2 = Claim(type=ClaimType.HYPOTHESIS, **kwargs)
        assert c1.cid() != c2.cid()

    def test_signature_excluded_from_cid(self):
        """Signature is not part of the content hash — it's metadata."""
        kwargs = dict(
            claim="Signed claim",
            type=ClaimType.RESULT,
            timestamp="2026-01-01T00:00:00Z",
        )
        unsigned = Claim(**kwargs)
        signed = Claim(signature="sig_abc123", **kwargs)
        assert unsigned.cid() == signed.cid()

    def test_parent_order_matters(self):
        """Different parent ordering = different canonical form = different CID."""
        base = dict(
            claim="test", type=ClaimType.RESULT, timestamp="2026-01-01T00:00:00Z"
        )
        c1 = Claim(parents=("a", "b"), **base)
        c2 = Claim(parents=("b", "a"), **base)
        assert c1.cid() != c2.cid()


class TestCanonicalForm:
    def test_canonical_bytes_sorted_keys(self, sample_claim):
        raw = sample_claim.canonical_bytes()
        parsed = json.loads(raw)
        keys = list(parsed.keys())
        assert keys == sorted(keys)

    def test_canonical_bytes_no_whitespace(self, sample_claim):
        raw = sample_claim.canonical_bytes()
        text = raw.decode("utf-8")
        # No spaces after colons or commas (compact JSON)
        assert ": " not in text
        assert ", " not in text

    def test_canonical_excludes_signature(self, sample_claim):
        raw = sample_claim.canonical_bytes()
        parsed = json.loads(raw)
        assert "signature" not in parsed

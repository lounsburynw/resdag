"""Tests for verification receipts."""

import json

import pytest

from resdag.claim import Claim, ClaimType
from resdag.dag import DAG
from resdag.storage.local import LocalStore
from resdag.verify.receipt import (
    VerificationReceipt,
    VerificationResult,
    create_receipt,
    parse_receipt,
    verification_status,
)


@pytest.fixture
def store(tmp_path):
    s = LocalStore(tmp_path / ".resdag")
    s.init()
    return s


@pytest.fixture
def dag(store):
    return DAG(store)


@pytest.fixture
def target_claim(dag):
    """A simple result claim to verify against."""
    claim = Claim(
        claim="Solar panel efficiency increases 12% with perovskite coating",
        type=ClaimType.RESULT,
        domain=("materials_science", "photovoltaics"),
        timestamp="2026-01-15T10:00:00Z",
    )
    cid = dag.add(claim)
    return cid


# --- VerificationResult enum ---


def test_verification_result_values():
    assert VerificationResult.VERIFIED.value == "verified"
    assert VerificationResult.UNVERIFIED.value == "unverified"
    assert VerificationResult.PARTIAL.value == "partial"


def test_verification_result_from_string():
    assert VerificationResult("verified") == VerificationResult.VERIFIED


# --- create_receipt ---


def test_create_receipt_basic(target_claim):
    receipt = create_receipt(
        target_cid=target_claim,
        result=VerificationResult.VERIFIED,
        method="double_blind_rct",
        description="Replicated on 200 held-out problems",
    )
    assert receipt.type == ClaimType.VERIFICATION
    assert receipt.parents == (target_claim,)
    payload = json.loads(receipt.claim)
    assert payload["result"] == "verified"
    assert payload["method"] == "double_blind_rct"
    assert payload["description"] == "Replicated on 200 held-out problems"
    assert "confidence" not in payload


def test_create_receipt_with_confidence(target_claim):
    receipt = create_receipt(
        target_cid=target_claim,
        result=VerificationResult.PARTIAL,
        method="statistical_reanalysis",
        confidence=0.75,
    )
    payload = json.loads(receipt.claim)
    assert payload["confidence"] == 0.75
    assert payload["result"] == "partial"


def test_create_receipt_confidence_validation(target_claim):
    with pytest.raises(ValueError, match="Confidence must be between"):
        create_receipt(
            target_cid=target_claim,
            result=VerificationResult.VERIFIED,
            method="test",
            confidence=1.5,
        )
    with pytest.raises(ValueError, match="Confidence must be between"):
        create_receipt(
            target_cid=target_claim,
            result=VerificationResult.VERIFIED,
            method="test",
            confidence=-0.1,
        )


def test_create_receipt_confidence_boundaries(target_claim):
    r0 = create_receipt(
        target_cid=target_claim, result=VerificationResult.VERIFIED,
        method="test", confidence=0.0,
    )
    r1 = create_receipt(
        target_cid=target_claim, result=VerificationResult.VERIFIED,
        method="test", confidence=1.0,
    )
    assert json.loads(r0.claim)["confidence"] == 0.0
    assert json.loads(r1.claim)["confidence"] == 1.0


def test_create_receipt_with_evidence(target_claim):
    receipt = create_receipt(
        target_cid=target_claim,
        result=VerificationResult.VERIFIED,
        method="code_review",
        evidence=("bafkreixxxx",),
    )
    assert receipt.evidence == ("bafkreixxxx",)


def test_create_receipt_with_domain(target_claim):
    receipt = create_receipt(
        target_cid=target_claim,
        result=VerificationResult.VERIFIED,
        method="peer_review",
        domain=("materials_science", "experiments"),
    )
    assert receipt.domain == ("materials_science", "experiments")


def test_create_receipt_with_author(target_claim):
    receipt = create_receipt(
        target_cid=target_claim,
        result=VerificationResult.VERIFIED,
        method="expert_review",
        author="did:key:z6Mktest123",
    )
    assert receipt.author == "did:key:z6Mktest123"


def test_create_receipt_with_timestamp(target_claim):
    receipt = create_receipt(
        target_cid=target_claim,
        result=VerificationResult.VERIFIED,
        method="test",
        timestamp="2026-03-01T12:00:00Z",
    )
    assert receipt.timestamp == "2026-03-01T12:00:00Z"


def test_receipt_is_a_claim(target_claim):
    """Verification receipt is just a Claim — stored in the DAG like any other."""
    receipt = create_receipt(
        target_cid=target_claim,
        result=VerificationResult.VERIFIED,
        method="statistical_reanalysis",
    )
    assert isinstance(receipt, Claim)
    assert receipt.cid()  # Has a valid CID


def test_receipt_cid_deterministic(target_claim):
    """Same receipt parameters produce the same CID."""
    kwargs = dict(
        target_cid=target_claim,
        result=VerificationResult.VERIFIED,
        method="test_method",
        description="Test",
        confidence=0.9,
        timestamp="2026-01-01T00:00:00Z",
    )
    r1 = create_receipt(**kwargs)
    r2 = create_receipt(**kwargs)
    assert r1.cid() == r2.cid()


def test_receipt_different_results_different_cids(target_claim):
    kwargs = dict(
        target_cid=target_claim,
        method="test",
        timestamp="2026-01-01T00:00:00Z",
    )
    verified = create_receipt(result=VerificationResult.VERIFIED, **kwargs)
    unverified = create_receipt(result=VerificationResult.UNVERIFIED, **kwargs)
    assert verified.cid() != unverified.cid()


# --- parse_receipt ---


def test_parse_receipt_roundtrip(target_claim):
    original = create_receipt(
        target_cid=target_claim,
        result=VerificationResult.VERIFIED,
        method="statistical_reanalysis",
        description="Confirmed via independent dataset",
        confidence=0.95,
    )
    parsed = parse_receipt(original)
    assert parsed.target_cid == target_claim
    assert parsed.result == VerificationResult.VERIFIED
    assert parsed.method == "statistical_reanalysis"
    assert parsed.description == "Confirmed via independent dataset"
    assert parsed.confidence == 0.95


def test_parse_receipt_without_confidence(target_claim):
    receipt = create_receipt(
        target_cid=target_claim,
        result=VerificationResult.UNVERIFIED,
        method="replication_attempt",
    )
    parsed = parse_receipt(receipt)
    assert parsed.confidence is None


def test_parse_receipt_wrong_type():
    claim = Claim(claim="Not a receipt", type=ClaimType.RESULT)
    with pytest.raises(ValueError, match="Not a verification claim"):
        parse_receipt(claim)


def test_parse_receipt_no_parents():
    claim = Claim(claim="{}", type=ClaimType.VERIFICATION)
    with pytest.raises(ValueError, match="no target"):
        parse_receipt(claim)


def test_parse_receipt_invalid_json():
    claim = Claim(
        claim="not json at all",
        type=ClaimType.VERIFICATION,
        parents=("bafkreixxxx",),
    )
    with pytest.raises(ValueError, match="Invalid verification receipt payload"):
        parse_receipt(claim)


# --- Serialization roundtrip through storage ---


def test_receipt_survives_storage_roundtrip(dag, target_claim):
    """Receipt stored in DAG and retrieved retains all fields."""
    receipt_claim = create_receipt(
        target_cid=target_claim,
        result=VerificationResult.VERIFIED,
        method="formal_proof",
        description="Lean 4 proof of convergence",
        confidence=1.0,
    )
    cid = dag.add(receipt_claim)
    restored = dag.get(cid)
    parsed = parse_receipt(restored)
    assert parsed.target_cid == target_claim
    assert parsed.result == VerificationResult.VERIFIED
    assert parsed.method == "formal_proof"
    assert parsed.description == "Lean 4 proof of convergence"
    assert parsed.confidence == 1.0


def test_receipt_json_roundtrip(target_claim):
    """Receipt survives JSON serialization/deserialization."""
    receipt = create_receipt(
        target_cid=target_claim,
        result=VerificationResult.PARTIAL,
        method="code_review",
        description="3 of 5 experiments replicated",
        confidence=0.6,
    )
    json_str = receipt.to_json()
    restored = Claim.from_json(json_str)
    parsed = parse_receipt(restored)
    assert parsed.result == VerificationResult.PARTIAL
    assert parsed.method == "code_review"
    assert parsed.confidence == 0.6


# --- verification_status query ---


def test_verification_status_no_receipts(dag, target_claim):
    receipts = verification_status(target_claim, dag)
    assert receipts == []


def test_verification_status_one_receipt(dag, target_claim):
    receipt = create_receipt(
        target_cid=target_claim,
        result=VerificationResult.VERIFIED,
        method="replication",
    )
    dag.add(receipt)
    receipts = verification_status(target_claim, dag)
    assert len(receipts) == 1
    assert receipts[0].result == VerificationResult.VERIFIED


def test_verification_status_multiple_receipts(dag, target_claim):
    """Multiple independent verifications of the same claim."""
    r1 = create_receipt(
        target_cid=target_claim,
        result=VerificationResult.VERIFIED,
        method="replication",
        author="did:key:z6Mkverifier1",
        timestamp="2026-02-01T00:00:00Z",
    )
    r2 = create_receipt(
        target_cid=target_claim,
        result=VerificationResult.PARTIAL,
        method="statistical_review",
        author="did:key:z6Mkverifier2",
        timestamp="2026-02-02T00:00:00Z",
    )
    r3 = create_receipt(
        target_cid=target_claim,
        result=VerificationResult.UNVERIFIED,
        method="replication_failure",
        author="did:key:z6Mkverifier3",
        timestamp="2026-02-03T00:00:00Z",
    )
    dag.add(r1)
    dag.add(r2)
    dag.add(r3)
    receipts = verification_status(target_claim, dag)
    assert len(receipts) == 3
    results = {r.result for r in receipts}
    assert results == {
        VerificationResult.VERIFIED,
        VerificationResult.PARTIAL,
        VerificationResult.UNVERIFIED,
    }


def test_verification_status_ignores_non_verification_children(dag, target_claim):
    """Non-verification children (e.g., replication claims) are not returned."""
    replication = Claim(
        claim="Aspirin reduces headache severity by 40%",
        type=ClaimType.REPLICATION,
        parents=(target_claim,),
        timestamp="2026-02-01T00:00:00Z",
    )
    receipt = create_receipt(
        target_cid=target_claim,
        result=VerificationResult.VERIFIED,
        method="replication",
        timestamp="2026-02-02T00:00:00Z",
    )
    dag.add(replication)
    dag.add(receipt)
    receipts = verification_status(target_claim, dag)
    assert len(receipts) == 1
    assert receipts[0].result == VerificationResult.VERIFIED


# --- Integration: receipt is a first-class DAG node ---


def test_receipt_has_ancestors_in_dag(dag, target_claim):
    """Receipt's ancestors include the target claim."""
    receipt = create_receipt(
        target_cid=target_claim,
        result=VerificationResult.VERIFIED,
        method="test",
    )
    receipt_cid = dag.add(receipt)
    ancestors = dag.ancestors(receipt_cid)
    assert target_claim in ancestors


def test_receipt_appears_as_child_of_target(dag, target_claim):
    receipt = create_receipt(
        target_cid=target_claim,
        result=VerificationResult.VERIFIED,
        method="test",
    )
    receipt_cid = dag.add(receipt)
    children = dag.children(target_claim)
    assert receipt_cid in children


def test_receipt_is_leaf(dag, target_claim):
    """A receipt with no children is a leaf node."""
    receipt = create_receipt(
        target_cid=target_claim,
        result=VerificationResult.VERIFIED,
        method="test",
    )
    dag.add(receipt)
    leaves = dag.leaves()
    # The receipt is a leaf; the target claim is no longer a leaf
    assert target_claim not in leaves


def test_receipt_can_be_signed(dag, target_claim):
    """Receipt can be signed like any other claim."""
    from resdag.identity import Identity

    identity = Identity.generate()
    receipt = create_receipt(
        target_cid=target_claim,
        result=VerificationResult.VERIFIED,
        method="expert_review",
        description="Methodology is sound",
    )
    signed = identity.sign(receipt)
    assert signed.author == identity.did
    assert signed.signature

    from resdag.identity import verify
    assert verify(signed)

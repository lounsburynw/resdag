"""Tests for equivalence claims."""

import json

import pytest

from resdag.claim import Claim, ClaimType
from resdag.dag import DAG
from resdag.storage.local import LocalStore
from resdag.discover.equivalence import (
    EquivalenceAssertion,
    create_equivalence,
    parse_equivalence,
    equivalence_cluster,
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
def claim_a(dag):
    """First result claim."""
    claim = Claim(
        claim="Grokking occurs after 10^4 training steps on modular arithmetic",
        type=ClaimType.RESULT,
        domain=("ml", "grokking"),
        timestamp="2026-01-01T00:00:00Z",
    )
    return dag.add(claim)


@pytest.fixture
def claim_b(dag):
    """Second result claim — semantically similar to claim_a."""
    claim = Claim(
        claim="Phase transition to generalization at ~10k steps in mod-p addition",
        type=ClaimType.RESULT,
        domain=("ml", "generalization"),
        timestamp="2026-01-02T00:00:00Z",
    )
    return dag.add(claim)


@pytest.fixture
def claim_c(dag):
    """Third result claim — for transitive equivalence tests."""
    claim = Claim(
        claim="Sudden generalization after extended memorization in modular tasks",
        type=ClaimType.RESULT,
        domain=("ml", "grokking"),
        timestamp="2026-01-03T00:00:00Z",
    )
    return dag.add(claim)


# --- create_equivalence ---


def test_create_equivalence_basic(claim_a, claim_b):
    eq = create_equivalence(
        cid_a=claim_a,
        cid_b=claim_b,
        scope="Same phenomenon described with different terminology",
    )
    assert eq.type == ClaimType.EQUIVALENCE
    assert eq.parents == (claim_a, claim_b)
    payload = json.loads(eq.claim)
    assert payload["scope"] == "Same phenomenon described with different terminology"
    assert payload["description"] == ""


def test_create_equivalence_with_description(claim_a, claim_b):
    eq = create_equivalence(
        cid_a=claim_a,
        cid_b=claim_b,
        scope="Quantitative threshold agreement",
        description="Both report ~10k steps; 10^4 ≈ 10k",
    )
    payload = json.loads(eq.claim)
    assert payload["description"] == "Both report ~10k steps; 10^4 ≈ 10k"


def test_create_equivalence_scope_required(claim_a, claim_b):
    with pytest.raises(ValueError, match="Scope is required"):
        create_equivalence(cid_a=claim_a, cid_b=claim_b, scope="")


def test_create_equivalence_with_evidence(claim_a, claim_b):
    eq = create_equivalence(
        cid_a=claim_a,
        cid_b=claim_b,
        scope="test",
        evidence=("bafkreixxxx",),
    )
    assert eq.evidence == ("bafkreixxxx",)


def test_create_equivalence_with_domain(claim_a, claim_b):
    eq = create_equivalence(
        cid_a=claim_a,
        cid_b=claim_b,
        scope="test",
        domain=("ml", "grokking"),
    )
    assert eq.domain == ("ml", "grokking")


def test_create_equivalence_with_author(claim_a, claim_b):
    eq = create_equivalence(
        cid_a=claim_a,
        cid_b=claim_b,
        scope="test",
        author="did:key:z6Mktest123",
    )
    assert eq.author == "did:key:z6Mktest123"


def test_create_equivalence_with_timestamp(claim_a, claim_b):
    eq = create_equivalence(
        cid_a=claim_a,
        cid_b=claim_b,
        scope="test",
        timestamp="2026-03-01T12:00:00Z",
    )
    assert eq.timestamp == "2026-03-01T12:00:00Z"


def test_equivalence_is_a_claim(claim_a, claim_b):
    eq = create_equivalence(cid_a=claim_a, cid_b=claim_b, scope="test")
    assert isinstance(eq, Claim)
    assert eq.cid()


def test_equivalence_cid_deterministic(claim_a, claim_b):
    kwargs = dict(
        cid_a=claim_a,
        cid_b=claim_b,
        scope="Same phenomenon",
        description="Test",
        timestamp="2026-01-01T00:00:00Z",
    )
    e1 = create_equivalence(**kwargs)
    e2 = create_equivalence(**kwargs)
    assert e1.cid() == e2.cid()


def test_equivalence_different_scope_different_cid(claim_a, claim_b):
    kwargs = dict(
        cid_a=claim_a,
        cid_b=claim_b,
        timestamp="2026-01-01T00:00:00Z",
    )
    e1 = create_equivalence(scope="quantitative agreement", **kwargs)
    e2 = create_equivalence(scope="qualitative agreement", **kwargs)
    assert e1.cid() != e2.cid()


# --- parse_equivalence ---


def test_parse_equivalence_roundtrip(claim_a, claim_b):
    original = create_equivalence(
        cid_a=claim_a,
        cid_b=claim_b,
        scope="Same grokking phenomenon",
        description="Both describe delayed generalization in modular arithmetic",
    )
    parsed = parse_equivalence(original)
    assert parsed.left_cid == claim_a
    assert parsed.right_cid == claim_b
    assert parsed.scope == "Same grokking phenomenon"
    assert parsed.description == "Both describe delayed generalization in modular arithmetic"


def test_parse_equivalence_without_description(claim_a, claim_b):
    eq = create_equivalence(cid_a=claim_a, cid_b=claim_b, scope="test")
    parsed = parse_equivalence(eq)
    assert parsed.description == ""


def test_parse_equivalence_wrong_type():
    claim = Claim(claim="Not an equivalence", type=ClaimType.RESULT)
    with pytest.raises(ValueError, match="Not an equivalence claim"):
        parse_equivalence(claim)


def test_parse_equivalence_wrong_parent_count():
    claim = Claim(
        claim='{"scope": "test"}',
        type=ClaimType.EQUIVALENCE,
        parents=("one_parent_only",),
    )
    with pytest.raises(ValueError, match="exactly 2 parents"):
        parse_equivalence(claim)


def test_parse_equivalence_no_parents():
    claim = Claim(claim='{"scope": "test"}', type=ClaimType.EQUIVALENCE)
    with pytest.raises(ValueError, match="exactly 2 parents"):
        parse_equivalence(claim)


def test_parse_equivalence_invalid_json():
    claim = Claim(
        claim="not json",
        type=ClaimType.EQUIVALENCE,
        parents=("cid_a", "cid_b"),
    )
    with pytest.raises(ValueError, match="Invalid equivalence claim payload"):
        parse_equivalence(claim)


def test_parse_equivalence_missing_scope():
    claim = Claim(
        claim='{"description": "no scope"}',
        type=ClaimType.EQUIVALENCE,
        parents=("cid_a", "cid_b"),
    )
    with pytest.raises(ValueError, match="missing required 'scope'"):
        parse_equivalence(claim)


# --- Serialization roundtrip through storage ---


def test_equivalence_survives_storage_roundtrip(dag, claim_a, claim_b):
    eq_claim = create_equivalence(
        cid_a=claim_a,
        cid_b=claim_b,
        scope="Same grokking threshold",
        description="Quantitative agreement on step count",
    )
    cid = dag.add(eq_claim)
    restored = dag.get(cid)
    parsed = parse_equivalence(restored)
    assert parsed.left_cid == claim_a
    assert parsed.right_cid == claim_b
    assert parsed.scope == "Same grokking threshold"


def test_equivalence_json_roundtrip(claim_a, claim_b):
    eq = create_equivalence(
        cid_a=claim_a,
        cid_b=claim_b,
        scope="Terminological equivalence",
        description="Different words, same concept",
    )
    json_str = eq.to_json()
    restored = Claim.from_json(json_str)
    parsed = parse_equivalence(restored)
    assert parsed.scope == "Terminological equivalence"
    assert parsed.description == "Different words, same concept"


# --- equivalence_cluster query ---


def test_equivalence_cluster_no_equivalences(dag, claim_a):
    cluster = equivalence_cluster(claim_a, dag)
    assert cluster == {claim_a}


def test_equivalence_cluster_single_pair(dag, claim_a, claim_b):
    eq = create_equivalence(
        cid_a=claim_a,
        cid_b=claim_b,
        scope="Same phenomenon",
    )
    dag.add(eq)
    cluster = equivalence_cluster(claim_a, dag)
    assert cluster == {claim_a, claim_b}


def test_equivalence_cluster_symmetric(dag, claim_a, claim_b):
    """Querying either side of an equivalence returns the same cluster."""
    eq = create_equivalence(cid_a=claim_a, cid_b=claim_b, scope="test")
    dag.add(eq)
    assert equivalence_cluster(claim_a, dag) == equivalence_cluster(claim_b, dag)


def test_equivalence_cluster_transitive(dag, claim_a, claim_b, claim_c):
    """If A≡B and B≡C, then querying A returns {A, B, C}."""
    eq_ab = create_equivalence(cid_a=claim_a, cid_b=claim_b, scope="scope 1")
    eq_bc = create_equivalence(cid_a=claim_b, cid_b=claim_c, scope="scope 2")
    dag.add(eq_ab)
    dag.add(eq_bc)
    cluster = equivalence_cluster(claim_a, dag)
    assert cluster == {claim_a, claim_b, claim_c}


def test_equivalence_cluster_transitive_from_end(dag, claim_a, claim_b, claim_c):
    """Transitive cluster reachable from any member."""
    eq_ab = create_equivalence(cid_a=claim_a, cid_b=claim_b, scope="scope 1")
    eq_bc = create_equivalence(cid_a=claim_b, cid_b=claim_c, scope="scope 2")
    dag.add(eq_ab)
    dag.add(eq_bc)
    assert equivalence_cluster(claim_c, dag) == {claim_a, claim_b, claim_c}


def test_equivalence_cluster_multiple_equivalences_same_pair(dag, claim_a, claim_b):
    """Multiple equivalence claims between same pair (different scopes) don't duplicate."""
    eq1 = create_equivalence(
        cid_a=claim_a, cid_b=claim_b, scope="quantitative",
        timestamp="2026-01-01T00:00:00Z",
    )
    eq2 = create_equivalence(
        cid_a=claim_a, cid_b=claim_b, scope="qualitative",
        timestamp="2026-01-02T00:00:00Z",
    )
    dag.add(eq1)
    dag.add(eq2)
    cluster = equivalence_cluster(claim_a, dag)
    assert cluster == {claim_a, claim_b}


def test_equivalence_cluster_ignores_non_equivalence_children(dag, claim_a, claim_b):
    """Non-equivalence children don't pollute the cluster."""
    replication = Claim(
        claim="Replicated grokking result",
        type=ClaimType.REPLICATION,
        parents=(claim_a,),
        timestamp="2026-02-01T00:00:00Z",
    )
    dag.add(replication)
    eq = create_equivalence(cid_a=claim_a, cid_b=claim_b, scope="test")
    dag.add(eq)
    cluster = equivalence_cluster(claim_a, dag)
    assert cluster == {claim_a, claim_b}


def test_equivalence_cluster_disjoint_clusters(dag, claim_a, claim_b, claim_c):
    """Disconnected equivalence pairs form separate clusters."""
    # Only A≡B, C is separate
    eq = create_equivalence(cid_a=claim_a, cid_b=claim_b, scope="test")
    dag.add(eq)
    assert equivalence_cluster(claim_a, dag) == {claim_a, claim_b}
    assert equivalence_cluster(claim_c, dag) == {claim_c}


# --- Integration: equivalence is a first-class DAG node ---


def test_equivalence_has_ancestors_in_dag(dag, claim_a, claim_b):
    eq = create_equivalence(cid_a=claim_a, cid_b=claim_b, scope="test")
    eq_cid = dag.add(eq)
    ancestors = dag.ancestors(eq_cid)
    assert claim_a in ancestors
    assert claim_b in ancestors


def test_equivalence_appears_as_child_of_both_parents(dag, claim_a, claim_b):
    eq = create_equivalence(cid_a=claim_a, cid_b=claim_b, scope="test")
    eq_cid = dag.add(eq)
    assert eq_cid in dag.children(claim_a)
    assert eq_cid in dag.children(claim_b)


def test_equivalence_is_leaf(dag, claim_a, claim_b):
    eq = create_equivalence(cid_a=claim_a, cid_b=claim_b, scope="test")
    eq_cid = dag.add(eq)
    leaves = dag.leaves()
    assert eq_cid in leaves
    assert claim_a not in leaves
    assert claim_b not in leaves


def test_equivalence_can_be_signed(dag, claim_a, claim_b):
    from resdag.identity import Identity, verify

    identity = Identity.generate()
    eq = create_equivalence(
        cid_a=claim_a,
        cid_b=claim_b,
        scope="Same grokking phenomenon",
    )
    signed = identity.sign(eq)
    assert signed.author == identity.did
    assert signed.signature
    assert verify(signed)

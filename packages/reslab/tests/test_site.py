"""Tests for site renderer."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from resdag.storage.local import LocalStore

from reslab import workflow
from reslab.site.renderer import generate_site
from reslab.vocabulary import Vocabulary, save_vocabulary


@pytest.fixture()
def store_with_dag(tmp_path: Path) -> tuple[LocalStore, Path]:
    """Create a store with a small research DAG."""
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", str(repo)], capture_output=True, check=True)
    subprocess.run(
        ["git", "-C", str(repo), "config", "user.email", "test@test.com"],
        capture_output=True,
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(repo), "config", "user.name", "Test"],
        capture_output=True,
        check=True,
    )
    dummy = repo / "README.md"
    dummy.write_text("init")
    subprocess.run(["git", "-C", str(repo), "add", "."], capture_output=True, check=True)
    subprocess.run(
        ["git", "-C", str(repo), "commit", "-m", "init"],
        capture_output=True,
        check=True,
    )

    store = LocalStore(str(tmp_path / ".resdag"))
    rp = str(repo)

    # Build a small DAG: hypothesis → result → refutation → new hypothesis
    h1 = workflow.hypothesize(store, "128-dim sufficient for depth-1", domains=["capacity"], repo_path=rp)

    ev_file = tmp_path / "result.json"
    ev_file.write_text(json.dumps({"accuracy": 0.975}))
    r1 = workflow.execute(
        store, "97.5% at depth-1", evidence_paths=[str(ev_file)],
        hypothesis_cid=h1, domains=["capacity"], repo_path=rp,
    )
    ref1 = workflow.interpret(
        store, "Confirmed at 128-dim", result_cid=r1, confirmed=True,
        domains=["capacity"], repo_path=rp,
    )
    h2 = workflow.branch(
        store, "Test 128-dim on depth-2", parent_cid=ref1,
        domains=["capacity", "composition"], repo_path=rp,
    )

    return store, tmp_path


def test_generates_index(store_with_dag: tuple[LocalStore, Path]) -> None:
    store, tmp_path = store_with_dag
    output = tmp_path / "site"
    count = generate_site(store, output)

    assert count == 4
    index = output / "index.html"
    assert index.exists()
    html = index.read_text()
    assert "Research DAG" in html
    assert "128-dim" in html


def test_generates_claim_pages(store_with_dag: tuple[LocalStore, Path]) -> None:
    store, tmp_path = store_with_dag
    output = tmp_path / "site"
    generate_site(store, output)

    claims_dir = output / "claims"
    assert claims_dir.exists()
    claim_files = list(claims_dir.glob("*.html"))
    assert len(claim_files) == 4


def test_index_has_dag_json(store_with_dag: tuple[LocalStore, Path]) -> None:
    store, tmp_path = store_with_dag
    output = tmp_path / "site"
    generate_site(store, output)

    html = (output / "index.html").read_text()
    # Should contain graph data for D3
    assert '"nodes"' in html
    assert '"links"' in html


def test_index_has_filter_buttons(store_with_dag: tuple[LocalStore, Path]) -> None:
    store, tmp_path = store_with_dag
    output = tmp_path / "site"
    generate_site(store, output)

    html = (output / "index.html").read_text()
    assert 'data-type="hypothesis"' in html
    assert 'data-type="result"' in html
    assert 'data-domain="capacity"' in html


def test_claim_page_has_lineage(store_with_dag: tuple[LocalStore, Path]) -> None:
    store, tmp_path = store_with_dag
    output = tmp_path / "site"
    generate_site(store, output)

    # Find a claim page that has parents (not the root hypothesis)
    for page in (output / "claims").glob("*.html"):
        html = page.read_text()
        if "Parents" in html:
            assert "badge-" in html  # parent type badge present
            return
    pytest.fail("No claim page found with parent lineage")


def test_claim_page_has_evidence(store_with_dag: tuple[LocalStore, Path]) -> None:
    store, tmp_path = store_with_dag
    output = tmp_path / "site"
    generate_site(store, output)

    for page in (output / "claims").glob("*.html"):
        html = page.read_text()
        if "Evidence" in html:
            assert "result.json" in html
            return
    pytest.fail("No claim page found with evidence")


def test_vocabulary_normalizes_filter_bar(store_with_dag: tuple[LocalStore, Path]) -> None:
    """When vocabulary exists, filter bar shows canonical tags and claims use normalized domains."""
    store, tmp_path = store_with_dag

    # The fixture uses domains=["capacity", "composition"].
    # Create a vocabulary where "capacity" is an alias for "scaling".
    vocab = Vocabulary(
        tags={"scaling": "Capacity and scaling", "composition": "Compositional structure"},
        aliases={"capacity": ["scaling"]},
    )
    save_vocabulary(vocab, store.root)

    output = tmp_path / "site"
    generate_site(store, output)

    html = (output / "index.html").read_text()
    # Filter bar should show canonical "scaling", not raw "capacity"
    assert 'data-domain="scaling"' in html
    assert 'data-domain="capacity"' not in html
    # Claims should have normalized domains in their data attributes
    assert 'scaling' in html


def test_no_vocabulary_shows_raw_tags(store_with_dag: tuple[LocalStore, Path]) -> None:
    """Without vocabulary, filter bar shows raw domain tags."""
    store, tmp_path = store_with_dag
    output = tmp_path / "site"
    generate_site(store, output)

    html = (output / "index.html").read_text()
    # Raw tags should appear
    assert 'data-domain="capacity"' in html


# --- Multi-select filter tests ---


def test_index_has_chip_container(store_with_dag: tuple[LocalStore, Path]) -> None:
    """Index page has the active-chips container for removable filter chips."""
    store, tmp_path = store_with_dag
    output = tmp_path / "site"
    generate_site(store, output)

    html = (output / "index.html").read_text()
    assert 'id="active-chips"' in html
    assert "active-chips" in html


def test_filter_js_uses_set_for_domains(store_with_dag: tuple[LocalStore, Path]) -> None:
    """JS filter uses a Set for multi-select domain tracking, not a single value."""
    store, tmp_path = store_with_dag
    output = tmp_path / "site"
    generate_site(store, output)

    html = (output / "index.html").read_text()
    # Must use Set for multi-select
    assert "new Set()" in html
    assert "activeDomains" in html
    # Must NOT have single-select activeDomain variable
    assert "let activeDomain = null" not in html


def test_filter_js_has_and_semantics(store_with_dag: tuple[LocalStore, Path]) -> None:
    """JS filter checks all active domains are present on the card (AND semantics)."""
    store, tmp_path = store_with_dag
    output = tmp_path / "site"
    generate_site(store, output)

    html = (output / "index.html").read_text()
    # AND semantics: iterate activeDomains, check each is in cardDomains
    assert "activeDomains.size" in html
    assert "cardDomains.includes(d)" in html


def test_filter_js_renders_chips(store_with_dag: tuple[LocalStore, Path]) -> None:
    """JS filter renders removable chip elements for active filters."""
    store, tmp_path = store_with_dag
    output = tmp_path / "site"
    generate_site(store, output)

    html = (output / "index.html").read_text()
    assert "renderChips" in html
    assert "chip-x" in html
    assert "removeDomain" in html


def test_multi_domain_claim_has_comma_separated_domains(
    store_with_dag: tuple[LocalStore, Path],
) -> None:
    """Claims with multiple domains store them as comma-separated data-domains attribute."""
    store, tmp_path = store_with_dag
    output = tmp_path / "site"
    generate_site(store, output)

    html = (output / "index.html").read_text()
    # h2 has domains=["capacity", "composition"] — should appear comma-separated
    assert 'data-domains="capacity,composition"' in html


def test_type_filter_remains_single_select(store_with_dag: tuple[LocalStore, Path]) -> None:
    """Type filter stays single-select (only one activeType at a time)."""
    store, tmp_path = store_with_dag
    output = tmp_path / "site"
    generate_site(store, output)

    html = (output / "index.html").read_text()
    # Type uses single value, not a Set
    assert "let activeType = null" in html
    assert "activeType === t ? null : t" in html


def test_visible_count_element_exists(store_with_dag: tuple[LocalStore, Path]) -> None:
    """Counter element exists and shows total count."""
    store, tmp_path = store_with_dag
    output = tmp_path / "site"
    generate_site(store, output)

    html = (output / "index.html").read_text()
    assert 'id="visible-count"' in html
    assert "4 of 4" in html

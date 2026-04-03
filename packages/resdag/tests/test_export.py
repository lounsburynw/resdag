"""Tests for subgraph export and static site generation."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from resdag.claim import Claim, ClaimType
from resdag.cli import main
from resdag.dag import DAG
from resdag.export.site import generate_site
from resdag.export.subgraph import (
    ExportResult,
    ancestor_closure,
    export_subgraph,
    read_manifest,
    select_claims,
    write_manifest,
)
from resdag.storage.local import LocalStore
from resdag.verify.receipt import VerificationResult, create_receipt


@pytest.fixture
def source_store(tmp_path):
    """Create a source store with a small DAG for testing.

    DAG structure:
        root_a (result, domain=physics)
        root_b (result, domain=topology)
        child_ab (hypothesis, domain=physics+topology, parents=[root_a, root_b])
        leaf (replication, domain=physics, parents=[child_ab])
    """
    store = LocalStore(tmp_path / "source")
    store.init()

    root_a = Claim(
        claim="Speed of light is constant",
        type=ClaimType.RESULT,
        domain=("physics",),
        timestamp="2026-01-15T10:00:00Z",
    )
    root_b = Claim(
        claim="Persistent homology detects phase transitions in lattice models",
        type=ClaimType.RESULT,
        domain=("topology",),
        timestamp="2026-02-20T12:00:00Z",
    )

    cid_a = store.put(root_a)
    cid_b = store.put(root_b)

    child_ab = Claim(
        claim="Topological invariants predict critical exponents in statistical mechanics",
        type=ClaimType.HYPOTHESIS,
        parents=(cid_a, cid_b),
        domain=("physics", "topology"),
        timestamp="2026-03-10T08:00:00Z",
    )
    cid_ab = store.put(child_ab)

    leaf = Claim(
        claim="Conservation principle replicated",
        type=ClaimType.REPLICATION,
        parents=(cid_ab,),
        domain=("physics",),
        timestamp="2026-04-01T14:00:00Z",
    )
    cid_leaf = store.put(leaf)

    return store, {
        "root_a": cid_a,
        "root_b": cid_b,
        "child_ab": cid_ab,
        "leaf": cid_leaf,
    }


@pytest.fixture
def target_store(tmp_path):
    store = LocalStore(tmp_path / "target")
    store.init()
    return store


# ── select_claims ─────────────────────────────────────────────────


class TestSelectClaims:
    def test_no_criteria_returns_empty(self, source_store):
        store, _ = source_store
        assert select_claims(store) == set()

    def test_select_by_cids(self, source_store):
        store, cids = source_store
        selected = select_claims(store, cids={cids["root_a"], cids["leaf"]})
        assert selected == {cids["root_a"], cids["leaf"]}

    def test_select_by_cids_ignores_unknown(self, source_store):
        store, cids = source_store
        selected = select_claims(store, cids={cids["root_a"], "nonexistent"})
        assert selected == {cids["root_a"]}

    def test_select_by_domain(self, source_store):
        store, cids = source_store
        selected = select_claims(store, domains={"topology"})
        assert selected == {cids["root_b"], cids["child_ab"]}

    def test_select_by_domain_physics(self, source_store):
        store, cids = source_store
        selected = select_claims(store, domains={"physics"})
        assert selected == {cids["root_a"], cids["child_ab"], cids["leaf"]}

    def test_select_by_date_after(self, source_store):
        store, cids = source_store
        selected = select_claims(store, after="2026-03-01T00:00:00Z")
        assert selected == {cids["child_ab"], cids["leaf"]}

    def test_select_by_date_before(self, source_store):
        store, cids = source_store
        selected = select_claims(store, before="2026-02-01T00:00:00Z")
        assert selected == {cids["root_a"]}

    def test_select_by_date_range(self, source_store):
        store, cids = source_store
        selected = select_claims(
            store, after="2026-02-01T00:00:00Z", before="2026-04-01T00:00:00Z"
        )
        assert selected == {cids["root_b"], cids["child_ab"]}

    def test_select_intersection_domain_and_date(self, source_store):
        store, cids = source_store
        selected = select_claims(
            store, domains={"physics"}, after="2026-03-01T00:00:00Z"
        )
        assert selected == {cids["child_ab"], cids["leaf"]}

    def test_select_intersection_cids_and_domain(self, source_store):
        store, cids = source_store
        selected = select_claims(
            store,
            cids={cids["root_a"], cids["root_b"]},
            domains={"topology"},
        )
        assert selected == {cids["root_b"]}


# ── ancestor_closure ──────────────────────────────────────────────


class TestAncestorClosure:
    def test_roots_have_no_ancestors(self, source_store):
        store, cids = source_store
        dag = DAG(store)
        result = ancestor_closure(dag, {cids["root_a"]})
        assert result == {cids["root_a"]}

    def test_leaf_closure_includes_all_ancestors(self, source_store):
        store, cids = source_store
        dag = DAG(store)
        result = ancestor_closure(dag, {cids["leaf"]})
        assert result == {
            cids["leaf"],
            cids["child_ab"],
            cids["root_a"],
            cids["root_b"],
        }

    def test_child_closure(self, source_store):
        store, cids = source_store
        dag = DAG(store)
        result = ancestor_closure(dag, {cids["child_ab"]})
        assert result == {cids["child_ab"], cids["root_a"], cids["root_b"]}

    def test_closure_of_multiple_cids(self, source_store):
        store, cids = source_store
        dag = DAG(store)
        result = ancestor_closure(dag, {cids["root_a"], cids["leaf"]})
        # root_a has no ancestors; leaf pulls in child_ab, root_a, root_b
        assert result == {
            cids["root_a"],
            cids["root_b"],
            cids["child_ab"],
            cids["leaf"],
        }


# ── export_subgraph ──────────────────────────────────────────────


class TestExportSubgraph:
    def test_export_single_root(self, source_store, target_store):
        store, cids = source_store
        result = export_subgraph(store, target_store, {cids["root_a"]})
        assert result.exported_cids == {cids["root_a"]}
        assert result.external_roots == set()
        assert target_store.has(cids["root_a"])

    def test_export_preserves_claim_content(self, source_store, target_store):
        store, cids = source_store
        export_subgraph(store, target_store, {cids["root_a"]})
        original = store.get(cids["root_a"])
        exported = target_store.get(cids["root_a"])
        assert original.claim == exported.claim
        assert original.type == exported.type
        assert original.cid() == exported.cid()

    def test_export_tracks_external_roots(self, source_store, target_store):
        store, cids = source_store
        # Export child without its parents
        result = export_subgraph(store, target_store, {cids["child_ab"]})
        assert result.external_roots == {cids["root_a"], cids["root_b"]}

    def test_exported_dag_has_no_unselected_claims(self, source_store, target_store):
        store, cids = source_store
        export_subgraph(store, target_store, {cids["root_a"], cids["child_ab"]})
        exported_cids = set(target_store.list_cids())
        assert cids["root_b"] not in exported_cids
        assert cids["leaf"] not in exported_cids

    def test_export_with_ancestor_closure_has_no_external_roots(
        self, source_store, target_store
    ):
        store, cids = source_store
        dag = DAG(store)
        full_set = ancestor_closure(dag, {cids["leaf"]})
        result = export_subgraph(store, target_store, full_set)
        assert result.external_roots == set()

    def test_export_partial_parents_tracks_missing(self, source_store, target_store):
        store, cids = source_store
        # Export child_ab + root_a but not root_b
        result = export_subgraph(
            store, target_store, {cids["child_ab"], cids["root_a"]}
        )
        assert result.external_roots == {cids["root_b"]}
        assert target_store.has(cids["child_ab"])
        assert target_store.has(cids["root_a"])
        assert not target_store.has(cids["root_b"])

    def test_export_chain(self, source_store, target_store):
        store, cids = source_store
        dag = DAG(store)
        # Export leaf + ancestor closure
        full_set = ancestor_closure(dag, {cids["leaf"]})
        result = export_subgraph(store, target_store, full_set)
        assert len(result.exported_cids) == 4
        assert result.external_roots == set()
        # Verify target DAG is traversable
        target_dag = DAG(target_store)
        assert set(target_dag.roots()) == {cids["root_a"], cids["root_b"]}
        assert set(target_dag.leaves()) == {cids["leaf"]}


# ── Evidence export ──────────────────────────────────────────────


class TestEvidenceExport:
    def test_evidence_not_included_by_default(self, source_store, target_store):
        store, cids = source_store
        # Attach evidence to root_a
        ev_cid = store.put_evidence(b"raw data", filename="data.csv")
        root_a = store.get(cids["root_a"])
        claim_with_ev = Claim(
            claim=root_a.claim,
            type=root_a.type,
            domain=root_a.domain,
            evidence=(ev_cid,),
            timestamp="2026-01-15T10:00:01Z",
        )
        cid_with_ev = store.put(claim_with_ev)

        result = export_subgraph(store, target_store, {cid_with_ev})
        assert result.evidence_cids == set()
        assert not target_store.has_evidence(ev_cid)

    def test_evidence_included_when_requested(self, source_store, target_store):
        store, cids = source_store
        ev_cid = store.put_evidence(
            b"experiment results", filename="results.json", media_type="application/json"
        )
        claim_with_ev = Claim(
            claim="Claim with evidence",
            type=ClaimType.RESULT,
            evidence=(ev_cid,),
            timestamp="2026-05-01T00:00:00Z",
        )
        cid_with_ev = store.put(claim_with_ev)

        result = export_subgraph(
            store, target_store, {cid_with_ev}, include_evidence=True
        )
        assert ev_cid in result.evidence_cids
        assert target_store.has_evidence(ev_cid)
        assert target_store.get_evidence(ev_cid) == b"experiment results"

    def test_evidence_metadata_preserved(self, source_store, target_store):
        store, _ = source_store
        ev_cid = store.put_evidence(
            b"data", filename="test.csv", media_type="text/csv"
        )
        claim = Claim(
            claim="With metadata",
            type=ClaimType.RESULT,
            evidence=(ev_cid,),
            timestamp="2026-05-01T00:00:00Z",
        )
        cid = store.put(claim)

        export_subgraph(store, target_store, {cid}, include_evidence=True)
        meta = target_store.get_evidence_meta(ev_cid)
        assert meta["filename"] == "test.csv"
        assert meta["media_type"] == "text/csv"


# ── Manifest ─────────────────────────────────────────────────────


class TestManifest:
    def test_write_and_read_roundtrip(self, tmp_path):
        result = ExportResult(
            exported_cids={"cid1", "cid2"},
            external_roots={"ext1"},
            evidence_cids={"ev1"},
        )
        manifest_path = tmp_path / "manifest.json"
        write_manifest(manifest_path, result)
        loaded = read_manifest(manifest_path)
        assert loaded.exported_cids == result.exported_cids
        assert loaded.external_roots == result.external_roots
        assert loaded.evidence_cids == result.evidence_cids

    def test_manifest_is_valid_json(self, tmp_path):
        result = ExportResult(
            exported_cids={"a", "b"},
            external_roots={"c"},
        )
        manifest_path = tmp_path / "manifest.json"
        write_manifest(manifest_path, result)
        data = json.loads(manifest_path.read_text())
        assert "exported_cids" in data
        assert "external_roots" in data
        assert "evidence_cids" in data

    def test_manifest_cids_are_sorted(self, tmp_path):
        result = ExportResult(
            exported_cids={"z", "a", "m"},
            external_roots=set(),
        )
        manifest_path = tmp_path / "manifest.json"
        write_manifest(manifest_path, result)
        data = json.loads(manifest_path.read_text())
        assert data["exported_cids"] == ["a", "m", "z"]

    def test_empty_manifest(self, tmp_path):
        result = ExportResult()
        manifest_path = tmp_path / "manifest.json"
        write_manifest(manifest_path, result)
        loaded = read_manifest(manifest_path)
        assert loaded.exported_cids == set()
        assert loaded.external_roots == set()
        assert loaded.evidence_cids == set()


# ── CLI ──────────────────────────────────────────────────────────


class TestExportCLI:
    @pytest.fixture
    def cli_env(self, tmp_path, monkeypatch):
        """Set up a resdag repo with claims for CLI testing."""
        monkeypatch.chdir(tmp_path)
        runner = CliRunner()
        runner.invoke(main, ["init"])
        runner.invoke(main, [
            "commit", "-c", "Root claim", "-t", "result", "-d", "physics",
        ])
        store = LocalStore(tmp_path / ".resdag")
        root_cid = store.list_cids()[0]
        runner.invoke(main, [
            "commit", "-c", "Child claim", "-t", "hypothesis",
            "-d", "physics", "-p", root_cid,
        ])
        child_cid = [c for c in store.list_cids() if c != root_cid][0]
        return runner, tmp_path, root_cid, child_cid

    def test_export_by_cid(self, cli_env):
        runner, tmp_path, root_cid, _ = cli_env
        out_dir = str(tmp_path / "exported")
        result = runner.invoke(main, ["export", out_dir, "-c", root_cid])
        assert result.exit_code == 0
        assert "Exported 1 claims" in result.output
        target = LocalStore(Path(out_dir))
        assert target.has(root_cid)

    def test_export_by_domain(self, cli_env):
        runner, tmp_path, _, _ = cli_env
        out_dir = str(tmp_path / "exported")
        result = runner.invoke(main, ["export", out_dir, "-d", "physics"])
        assert result.exit_code == 0
        assert "Exported 2 claims" in result.output

    def test_export_with_ancestors(self, cli_env):
        runner, tmp_path, root_cid, child_cid = cli_env
        out_dir = str(tmp_path / "exported")
        result = runner.invoke(main, [
            "export", out_dir, "-c", child_cid, "--include-ancestors",
        ])
        assert result.exit_code == 0
        assert "Exported 2 claims" in result.output
        target = LocalStore(Path(out_dir))
        assert target.has(root_cid)
        assert target.has(child_cid)

    def test_export_writes_manifest(self, cli_env):
        runner, tmp_path, root_cid, _ = cli_env
        out_dir = str(tmp_path / "exported")
        runner.invoke(main, ["export", out_dir, "-c", root_cid])
        manifest = json.loads((Path(out_dir) / "manifest.json").read_text())
        assert root_cid in manifest["exported_cids"]

    def test_export_no_match_fails(self, cli_env):
        runner, tmp_path, _, _ = cli_env
        out_dir = str(tmp_path / "exported")
        result = runner.invoke(main, ["export", out_dir, "-c", "nonexistent"])
        assert result.exit_code != 0

    def test_export_external_roots_reported(self, cli_env):
        runner, tmp_path, _, child_cid = cli_env
        out_dir = str(tmp_path / "exported")
        result = runner.invoke(main, ["export", out_dir, "-c", child_cid])
        assert result.exit_code == 0
        assert "1 external root" in result.output


# ── Static Site Generator ────────────────────────────────────────


class TestGenerateSite:
    def test_generates_index_html(self, source_store, tmp_path):
        store, _ = source_store
        out = tmp_path / "site"
        generate_site(store, out)
        assert (out / "index.html").exists()

    def test_generates_claim_pages(self, source_store, tmp_path):
        store, cids = source_store
        out = tmp_path / "site"
        count = generate_site(store, out)
        assert count == 4
        for cid in cids.values():
            assert (out / "claims" / f"{cid}.html").exists()

    def test_generates_domain_pages(self, source_store, tmp_path):
        store, _ = source_store
        out = tmp_path / "site"
        generate_site(store, out)
        assert (out / "domains" / "physics.html").exists()
        assert (out / "domains" / "topology.html").exists()

    def test_index_contains_claim_text(self, source_store, tmp_path):
        store, _ = source_store
        out = tmp_path / "site"
        generate_site(store, out)
        index = (out / "index.html").read_text()
        assert "Speed of light is constant" in index
        assert "Persistent homology detects phase transitions in lattice models" in index

    def test_index_contains_claim_count(self, source_store, tmp_path):
        store, _ = source_store
        out = tmp_path / "site"
        generate_site(store, out)
        index = (out / "index.html").read_text()
        assert "4 claims" in index

    def test_index_links_to_domain_pages(self, source_store, tmp_path):
        store, _ = source_store
        out = tmp_path / "site"
        generate_site(store, out)
        index = (out / "index.html").read_text()
        assert "domains/physics.html" in index
        assert "domains/topology.html" in index

    def test_claim_page_has_parent_links(self, source_store, tmp_path):
        store, cids = source_store
        out = tmp_path / "site"
        generate_site(store, out)
        child_html = (out / "claims" / f"{cids['child_ab']}.html").read_text()
        # Should link to both parents
        assert f"{cids['root_a']}.html" in child_html
        assert f"{cids['root_b']}.html" in child_html
        assert "Speed of light is constant" in child_html

    def test_claim_page_has_child_links(self, source_store, tmp_path):
        store, cids = source_store
        out = tmp_path / "site"
        generate_site(store, out)
        child_ab_html = (out / "claims" / f"{cids['child_ab']}.html").read_text()
        # child_ab should link to leaf as a child
        assert f"{cids['leaf']}.html" in child_ab_html

    def test_claim_page_has_domain_tags(self, source_store, tmp_path):
        store, cids = source_store
        out = tmp_path / "site"
        generate_site(store, out)
        child_html = (out / "claims" / f"{cids['child_ab']}.html").read_text()
        assert "physics" in child_html
        assert "topology" in child_html

    def test_claim_page_has_back_link(self, source_store, tmp_path):
        store, cids = source_store
        out = tmp_path / "site"
        generate_site(store, out)
        claim_html = (out / "claims" / f"{cids['root_a']}.html").read_text()
        assert "../index.html" in claim_html

    def test_claim_page_shows_type(self, source_store, tmp_path):
        store, cids = source_store
        out = tmp_path / "site"
        generate_site(store, out)
        root_html = (out / "claims" / f"{cids['root_a']}.html").read_text()
        assert "result" in root_html

    def test_domain_page_lists_matching_claims(self, source_store, tmp_path):
        store, cids = source_store
        out = tmp_path / "site"
        generate_site(store, out)
        physics = (out / "domains" / "physics.html").read_text()
        assert "Speed of light is constant" in physics
        assert "Conservation principle replicated" in physics
        # topology-only claim should not be on physics page
        assert "Persistent homology" not in physics

    def test_domain_page_has_back_link(self, source_store, tmp_path):
        store, _ = source_store
        out = tmp_path / "site"
        generate_site(store, out)
        physics = (out / "domains" / "physics.html").read_text()
        assert "../index.html" in physics

    def test_empty_store_generates_empty_site(self, tmp_path):
        store = LocalStore(tmp_path / "empty")
        store.init()
        out = tmp_path / "site"
        count = generate_site(store, out)
        assert count == 0
        assert (out / "index.html").exists()
        index = (out / "index.html").read_text()
        assert "0 claims" in index

    def test_returns_claim_count(self, source_store, tmp_path):
        store, _ = source_store
        out = tmp_path / "site"
        count = generate_site(store, out)
        assert count == 4

    def test_index_is_valid_html(self, source_store, tmp_path):
        store, _ = source_store
        out = tmp_path / "site"
        generate_site(store, out)
        index = (out / "index.html").read_text()
        assert index.startswith("<!DOCTYPE html>")
        assert "</html>" in index


class TestSiteVerification:
    def test_verification_receipts_shown(self, tmp_path):
        store = LocalStore(tmp_path / "store")
        store.init()
        dag = DAG(store)

        root = Claim(claim="Tested claim", type=ClaimType.RESULT)
        root_cid = dag.add(root)

        receipt = create_receipt(
            root_cid,
            VerificationResult.VERIFIED,
            method="manual review",
            description="Checked by expert",
        )
        dag.add(receipt)

        out = tmp_path / "site"
        generate_site(store, out)
        root_html = (out / "claims" / f"{root_cid}.html").read_text()
        assert "verified" in root_html
        assert "manual review" in root_html
        assert "Checked by expert" in root_html


class TestSiteEvidence:
    def test_evidence_metadata_shown(self, tmp_path):
        store = LocalStore(tmp_path / "store")
        store.init()

        ev_cid = store.put_evidence(
            b"col1,col2\n1,2\n", filename="data.csv", media_type="text/csv"
        )
        claim = Claim(
            claim="Claim with evidence",
            type=ClaimType.RESULT,
            evidence=(ev_cid,),
        )
        cid = store.put(claim)

        out = tmp_path / "site"
        generate_site(store, out)
        claim_html = (out / "claims" / f"{cid}.html").read_text()
        assert "data.csv" in claim_html
        assert "text/csv" in claim_html


class TestSiteCLI:
    @pytest.fixture
    def site_env(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        runner = CliRunner()
        runner.invoke(main, ["init"])
        runner.invoke(main, [
            "commit", "-c", "First claim", "-t", "result", "-d", "physics",
        ])
        runner.invoke(main, [
            "commit", "-c", "Second claim", "-t", "hypothesis", "-d", "topology",
        ])
        return runner, tmp_path

    def test_export_site_creates_html(self, site_env):
        runner, tmp_path = site_env
        out_dir = str(tmp_path / "mysite")
        result = runner.invoke(main, ["export", out_dir, "--site"])
        assert result.exit_code == 0
        assert "Generated site" in result.output
        assert "2 claim pages" in result.output
        assert (Path(out_dir) / "index.html").exists()
        assert (Path(out_dir) / "claims").is_dir()

    def test_export_site_singular_claim(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        runner = CliRunner()
        runner.invoke(main, ["init"])
        runner.invoke(main, [
            "commit", "-c", "Only claim", "-t", "result",
        ])
        out_dir = str(tmp_path / "mysite")
        result = runner.invoke(main, ["export", out_dir, "--site"])
        assert result.exit_code == 0
        assert "1 claim page" in result.output

    def test_export_site_no_repo_fails(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        runner = CliRunner()
        out_dir = str(tmp_path / "mysite")
        result = runner.invoke(main, ["export", out_dir, "--site"])
        assert result.exit_code != 0

    def test_export_site_serveable(self, site_env):
        runner, tmp_path = site_env
        out_dir = str(tmp_path / "mysite")
        runner.invoke(main, ["export", out_dir, "--site"])
        # All HTML files exist and are non-empty
        for html_file in Path(out_dir).rglob("*.html"):
            assert html_file.stat().st_size > 0

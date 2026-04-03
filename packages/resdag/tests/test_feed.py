"""Tests for Atom feed generation."""

from __future__ import annotations

from pathlib import Path
from xml.etree.ElementTree import parse as parse_xml

import pytest
from click.testing import CliRunner

from resdag.claim import Claim, ClaimType
from resdag.cli import main
from resdag.export.feed import generate_feed
from resdag.storage.local import LocalStore

ATOM_NS = "http://www.w3.org/2005/Atom"


def _ns(tag: str) -> str:
    """Wrap a tag name with the Atom namespace."""
    return f"{{{ATOM_NS}}}{tag}"


@pytest.fixture
def store_with_claims(tmp_path):
    """Store with 3 claims across 2 domains."""
    store = LocalStore(tmp_path / "store")
    store.init()

    c1 = Claim(
        claim="Speed of light is constant",
        type=ClaimType.RESULT,
        domain=("physics",),
        author="did:key:alice",
        timestamp="2026-01-15T10:00:00Z",
    )
    c2 = Claim(
        claim="Persistent homology detects phase transitions in lattice models",
        type=ClaimType.RESULT,
        domain=("topology",),
        timestamp="2026-02-20T12:00:00Z",
    )
    cid1 = store.put(c1)
    cid2 = store.put(c2)

    c3 = Claim(
        claim="Conservation principles are universal",
        type=ClaimType.HYPOTHESIS,
        domain=("physics", "topology"),
        parents=(cid1, cid2),
        timestamp="2026-03-10T08:00:00Z",
    )
    cid3 = store.put(c3)

    return store, {"c1": cid1, "c2": cid2, "c3": cid3}


# ── Core feed generation ──────────────────────────────────────────


class TestGenerateFeed:
    def test_generates_xml_file(self, store_with_claims, tmp_path):
        store, _ = store_with_claims
        feed_path = tmp_path / "out" / "feed.xml"
        generate_feed(store, feed_path)
        assert feed_path.exists()

    def test_returns_entry_count(self, store_with_claims, tmp_path):
        store, _ = store_with_claims
        count = generate_feed(store, tmp_path / "feed.xml")
        assert count == 3

    def test_valid_atom_structure(self, store_with_claims, tmp_path):
        store, _ = store_with_claims
        feed_path = tmp_path / "feed.xml"
        generate_feed(store, feed_path)
        tree = parse_xml(feed_path)
        root = tree.getroot()
        assert root.tag == _ns("feed")
        assert root.find(_ns("title")) is not None
        assert root.find(_ns("id")) is not None
        assert root.find(_ns("updated")) is not None

    def test_entries_have_required_fields(self, store_with_claims, tmp_path):
        store, _ = store_with_claims
        feed_path = tmp_path / "feed.xml"
        generate_feed(store, feed_path)
        tree = parse_xml(feed_path)
        entries = tree.getroot().findall(_ns("entry"))
        assert len(entries) == 3
        for entry in entries:
            assert entry.find(_ns("title")) is not None
            assert entry.find(_ns("id")) is not None
            assert entry.find(_ns("updated")) is not None

    def test_entries_sorted_newest_first(self, store_with_claims, tmp_path):
        store, _ = store_with_claims
        feed_path = tmp_path / "feed.xml"
        generate_feed(store, feed_path)
        tree = parse_xml(feed_path)
        entries = tree.getroot().findall(_ns("entry"))
        timestamps = [e.find(_ns("updated")).text for e in entries]
        assert timestamps == sorted(timestamps, reverse=True)

    def test_entry_title_includes_type(self, store_with_claims, tmp_path):
        store, _ = store_with_claims
        feed_path = tmp_path / "feed.xml"
        generate_feed(store, feed_path)
        tree = parse_xml(feed_path)
        entries = tree.getroot().findall(_ns("entry"))
        titles = [e.find(_ns("title")).text for e in entries]
        assert any("[result]" in t for t in titles)
        assert any("[hypothesis]" in t for t in titles)

    def test_entry_id_contains_cid(self, store_with_claims, tmp_path):
        store, cids = store_with_claims
        feed_path = tmp_path / "feed.xml"
        generate_feed(store, feed_path)
        tree = parse_xml(feed_path)
        entries = tree.getroot().findall(_ns("entry"))
        ids = [e.find(_ns("id")).text for e in entries]
        for cid in cids.values():
            assert any(cid in eid for eid in ids)

    def test_feed_updated_is_newest_claim(self, store_with_claims, tmp_path):
        store, _ = store_with_claims
        feed_path = tmp_path / "feed.xml"
        generate_feed(store, feed_path)
        tree = parse_xml(feed_path)
        updated = tree.getroot().find(_ns("updated")).text
        assert updated == "2026-03-10T08:00:00Z"

    def test_custom_title(self, store_with_claims, tmp_path):
        store, _ = store_with_claims
        feed_path = tmp_path / "feed.xml"
        generate_feed(store, feed_path, title="My Research")
        tree = parse_xml(feed_path)
        assert tree.getroot().find(_ns("title")).text == "My Research"


# ── Domain filtering ──────────────────────────────────────────────


class TestFeedDomainFilter:
    def test_filter_by_single_domain(self, store_with_claims, tmp_path):
        store, cids = store_with_claims
        feed_path = tmp_path / "feed.xml"
        count = generate_feed(store, feed_path, domain_filter={"topology"})
        assert count == 2  # c2 (topology) + c3 (physics, topology)

    def test_filter_excludes_non_matching(self, store_with_claims, tmp_path):
        store, cids = store_with_claims
        feed_path = tmp_path / "feed.xml"
        generate_feed(store, feed_path, domain_filter={"topology"})
        tree = parse_xml(feed_path)
        entries = tree.getroot().findall(_ns("entry"))
        titles = [e.find(_ns("title")).text for e in entries]
        assert not any("Speed of light" in t for t in titles)

    def test_no_filter_includes_all(self, store_with_claims, tmp_path):
        store, _ = store_with_claims
        feed_path = tmp_path / "feed.xml"
        count = generate_feed(store, feed_path)
        assert count == 3


# ── Author and categories ────────────────────────────────────────


class TestFeedMetadata:
    def test_author_included_when_present(self, store_with_claims, tmp_path):
        store, _ = store_with_claims
        feed_path = tmp_path / "feed.xml"
        generate_feed(store, feed_path)
        tree = parse_xml(feed_path)
        entries = tree.getroot().findall(_ns("entry"))
        authors = [
            e.find(_ns("author"))
            for e in entries
            if e.find(_ns("author")) is not None
        ]
        assert len(authors) == 1  # Only c1 has an author
        assert authors[0].find(_ns("name")).text == "did:key:alice"

    def test_domain_tags_as_categories(self, store_with_claims, tmp_path):
        store, _ = store_with_claims
        feed_path = tmp_path / "feed.xml"
        generate_feed(store, feed_path)
        tree = parse_xml(feed_path)
        entries = tree.getroot().findall(_ns("entry"))
        # Find the hypothesis entry (has both physics and topology)
        for entry in entries:
            if "hypothesis" in entry.find(_ns("title")).text:
                cats = entry.findall(_ns("category"))
                terms = {c.get("term") for c in cats}
                assert terms == {"physics", "topology"}
                break
        else:
            pytest.fail("hypothesis entry not found")


# ── Base URL ──────────────────────────────────────────────────────


class TestFeedBaseUrl:
    def test_no_links_without_base_url(self, store_with_claims, tmp_path):
        store, _ = store_with_claims
        feed_path = tmp_path / "feed.xml"
        generate_feed(store, feed_path)
        tree = parse_xml(feed_path)
        links = tree.getroot().findall(_ns("link"))
        assert len(links) == 0

    def test_feed_links_with_base_url(self, store_with_claims, tmp_path):
        store, _ = store_with_claims
        feed_path = tmp_path / "feed.xml"
        generate_feed(store, feed_path, base_url="https://example.com")
        tree = parse_xml(feed_path)
        links = tree.getroot().findall(_ns("link"))
        hrefs = {l.get("rel"): l.get("href") for l in links}
        assert hrefs["alternate"] == "https://example.com"
        assert hrefs["self"] == "https://example.com/feed.xml"

    def test_entry_links_with_base_url(self, store_with_claims, tmp_path):
        store, cids = store_with_claims
        feed_path = tmp_path / "feed.xml"
        generate_feed(store, feed_path, base_url="https://example.com")
        tree = parse_xml(feed_path)
        entries = tree.getroot().findall(_ns("entry"))
        for entry in entries:
            link = entry.find(_ns("link"))
            assert link is not None
            href = link.get("href")
            assert href.startswith("https://example.com/claims/")
            assert href.endswith(".html")


# ── Edge cases ────────────────────────────────────────────────────


class TestFeedEdgeCases:
    def test_empty_store(self, tmp_path):
        store = LocalStore(tmp_path / "empty")
        store.init()
        feed_path = tmp_path / "feed.xml"
        count = generate_feed(store, feed_path)
        assert count == 0
        tree = parse_xml(feed_path)
        assert tree.getroot().find(_ns("updated")) is not None
        assert len(tree.getroot().findall(_ns("entry"))) == 0

    def test_domain_filter_no_matches(self, store_with_claims, tmp_path):
        store, _ = store_with_claims
        feed_path = tmp_path / "feed.xml"
        count = generate_feed(store, feed_path, domain_filter={"chemistry"})
        assert count == 0

    def test_creates_parent_directories(self, store_with_claims, tmp_path):
        store, _ = store_with_claims
        feed_path = tmp_path / "deep" / "nested" / "feed.xml"
        generate_feed(store, feed_path)
        assert feed_path.exists()


# ── CLI ──────────────────────────────────────────────────────────


class TestFeedCLI:
    @pytest.fixture
    def cli_env(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        runner = CliRunner()
        runner.invoke(main, ["init"])
        runner.invoke(main, [
            "commit", "-c", "First result", "-t", "result", "-d", "physics",
        ])
        runner.invoke(main, [
            "commit", "-c", "Second result", "-t", "hypothesis", "-d", "topology",
        ])
        return runner, tmp_path

    def test_export_feed_creates_xml(self, cli_env):
        runner, tmp_path = cli_env
        out_dir = str(tmp_path / "out")
        result = runner.invoke(main, ["export", out_dir, "--feed"])
        assert result.exit_code == 0
        assert "Generated feed" in result.output
        assert "2 entries" in result.output
        assert (Path(out_dir) / "feed.xml").exists()

    def test_export_feed_singular_entry(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        runner = CliRunner()
        runner.invoke(main, ["init"])
        runner.invoke(main, ["commit", "-c", "Only claim", "-t", "result"])
        out_dir = str(tmp_path / "out")
        result = runner.invoke(main, ["export", out_dir, "--feed"])
        assert result.exit_code == 0
        assert "1 entry" in result.output

    def test_export_feed_with_domain_filter(self, cli_env):
        runner, tmp_path = cli_env
        out_dir = str(tmp_path / "out")
        result = runner.invoke(main, ["export", out_dir, "--feed", "-d", "physics"])
        assert result.exit_code == 0
        assert "1 entr" in result.output

    def test_export_feed_with_title(self, cli_env):
        runner, tmp_path = cli_env
        out_dir = str(tmp_path / "out")
        result = runner.invoke(main, [
            "export", out_dir, "--feed", "--feed-title", "My Research",
        ])
        assert result.exit_code == 0
        feed_path = Path(out_dir) / "feed.xml"
        tree = parse_xml(feed_path)
        assert tree.getroot().find(_ns("title")).text == "My Research"

    def test_export_feed_with_base_url(self, cli_env):
        runner, tmp_path = cli_env
        out_dir = str(tmp_path / "out")
        result = runner.invoke(main, [
            "export", out_dir, "--feed", "--base-url", "https://example.com",
        ])
        assert result.exit_code == 0
        feed_path = Path(out_dir) / "feed.xml"
        tree = parse_xml(feed_path)
        links = tree.getroot().findall(_ns("link"))
        assert len(links) == 2

    def test_export_site_and_feed_together(self, cli_env):
        runner, tmp_path = cli_env
        out_dir = str(tmp_path / "out")
        result = runner.invoke(main, ["export", out_dir, "--site", "--feed"])
        assert result.exit_code == 0
        assert "Generated feed" in result.output
        assert "Generated site" in result.output
        assert (Path(out_dir) / "feed.xml").exists()
        assert (Path(out_dir) / "index.html").exists()

    def test_export_feed_no_repo_fails(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        runner = CliRunner()
        result = runner.invoke(main, ["export", str(tmp_path / "out"), "--feed"])
        assert result.exit_code != 0

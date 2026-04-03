"""Tests that the project scaffold is complete and importable."""

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src" / "resdag"


def test_top_level_modules_exist():
    for name in ("claim", "dag", "evidence", "identity", "cli"):
        assert (SRC / f"{name}.py").is_file(), f"Missing {name}.py"


def test_subpackages_exist():
    for pkg in ("storage", "sync", "verify", "discover", "export"):
        pkg_dir = SRC / pkg
        assert pkg_dir.is_dir(), f"Missing package {pkg}/"
        assert (pkg_dir / "__init__.py").is_file(), f"Missing {pkg}/__init__.py"


def test_storage_modules():
    for name in ("local", "git", "ipfs"):
        assert (SRC / "storage" / f"{name}.py").is_file()


def test_sync_modules():
    for name in ("gossip", "remote"):
        assert (SRC / "sync" / f"{name}.py").is_file()


def test_verify_modules():
    for name in ("receipt", "formal", "consistency"):
        assert (SRC / "verify" / f"{name}.py").is_file()


def test_discover_modules():
    for name in ("embeddings", "equivalence", "search"):
        assert (SRC / "discover" / f"{name}.py").is_file()


def test_export_modules():
    for name in ("site", "feed", "markdown"):
        assert (SRC / "export" / f"{name}.py").is_file()


def test_pyproject_toml_exists():
    assert (ROOT / "pyproject.toml").is_file()


def test_import_resdag():
    import resdag
    assert hasattr(resdag, "__version__")


def test_import_subpackages():
    import resdag.storage
    import resdag.sync
    import resdag.verify
    import resdag.discover
    import resdag.export


def test_import_all_modules():
    import resdag.claim
    import resdag.dag
    import resdag.evidence
    import resdag.identity
    import resdag.cli
    import resdag.storage.local
    import resdag.storage.git
    import resdag.storage.ipfs
    import resdag.sync.gossip
    import resdag.sync.remote
    import resdag.verify.receipt
    import resdag.verify.formal
    import resdag.verify.consistency
    import resdag.discover.embeddings
    import resdag.discover.equivalence
    import resdag.discover.search
    import resdag.export.site
    import resdag.export.feed
    import resdag.export.markdown

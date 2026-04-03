"""Tests for the ResDAG CLI."""

import os

from click.testing import CliRunner

from resdag.cli import main


def test_init_creates_resdag_dir(tmp_path):
    runner = CliRunner()
    os.chdir(tmp_path)
    result = runner.invoke(main, ["init"])
    assert result.exit_code == 0
    assert "Initialized" in result.output
    assert (tmp_path / ".resdag" / "objects").is_dir()
    assert (tmp_path / ".resdag" / "GUIDE.md").is_file()


def test_guide_prints_usage(tmp_path):
    runner = CliRunner()
    result = runner.invoke(main, ["guide"])
    assert result.exit_code == 0
    assert "ResDAG Guide" in result.output
    assert "res commit" in result.output
    assert "For AI Tools" in result.output


def test_init_already_initialized(tmp_path):
    runner = CliRunner()
    os.chdir(tmp_path)
    runner.invoke(main, ["init"])
    result = runner.invoke(main, ["init"])
    assert result.exit_code == 0
    assert "Already initialized" in result.output


def test_commit_with_timestamp(tmp_path):
    runner = CliRunner()
    os.chdir(tmp_path)
    runner.invoke(main, ["init"])
    result = runner.invoke(main, [
        "commit", "-c", "Historical finding", "-t", "result",
        "-T", "2025-06-15T10:30:00Z",
    ])
    assert result.exit_code == 0
    # Verify the timestamp was set by showing the claim
    cid = result.output.strip().split("]")[0].lstrip("[")
    show_result = runner.invoke(main, ["show", cid])
    assert "2025-06-15T10:30:00Z" in show_result.output


def test_commit_creates_claim(tmp_path):
    runner = CliRunner()
    os.chdir(tmp_path)
    runner.invoke(main, ["init"])
    result = runner.invoke(main, [
        "commit", "-c", "Aspirin reduces headaches", "-t", "result",
    ])
    assert result.exit_code == 0
    assert "result" in result.output
    assert "Aspirin reduces headaches" in result.output


def test_commit_with_domain_and_author(tmp_path):
    runner = CliRunner()
    os.chdir(tmp_path)
    runner.invoke(main, ["init"])
    result = runner.invoke(main, [
        "commit",
        "-c", "Caffeine improves alertness",
        "-t", "hypothesis",
        "-d", "neuroscience",
        "-d", "cognition",
        "-a", "did:key:z6Mk1234",
    ])
    assert result.exit_code == 0
    assert "hypothesis" in result.output


def test_commit_with_parent(tmp_path):
    runner = CliRunner()
    os.chdir(tmp_path)
    runner.invoke(main, ["init"])
    # Create root claim
    result1 = runner.invoke(main, [
        "commit", "-c", "Base finding", "-t", "result",
    ])
    assert result1.exit_code == 0
    # Extract CID from log
    log_result = runner.invoke(main, ["log"])
    full_line = log_result.output.strip()
    # Get the full CID via show
    short_cid = full_line.split()[0]
    show_result = runner.invoke(main, ["show", short_cid])
    cid_line = [l for l in show_result.output.splitlines() if l.startswith("CID:")][0]
    full_cid = cid_line.split(maxsplit=1)[1].strip()
    # Create child claim
    result2 = runner.invoke(main, [
        "commit", "-c", "Follow-up result", "-t", "replication",
        "-p", full_cid,
    ])
    assert result2.exit_code == 0
    assert "replication" in result2.output


def test_commit_with_short_cid_parent(tmp_path):
    """res commit -p accepts short CIDs from res log output."""
    runner = CliRunner()
    os.chdir(tmp_path)
    runner.invoke(main, ["init"])
    runner.invoke(main, ["commit", "-c", "Root finding", "-t", "result"])
    # Get the short CID from log (12 chars)
    log_result = runner.invoke(main, ["log"])
    short_cid = log_result.output.strip().split()[0]
    assert len(short_cid) == 12
    # Use short CID as parent — should resolve
    result = runner.invoke(main, [
        "commit", "-c", "Builds on root", "-t", "replication",
        "-p", short_cid,
    ])
    assert result.exit_code == 0
    assert "replication" in result.output


def test_commit_missing_parent_fails(tmp_path):
    runner = CliRunner()
    os.chdir(tmp_path)
    runner.invoke(main, ["init"])
    result = runner.invoke(main, [
        "commit", "-c", "Orphan claim", "-t", "result",
        "-p", "nonexistent_cid",
    ])
    assert result.exit_code != 0
    assert "Parent not found" in result.output


def test_commit_without_init_fails(tmp_path):
    runner = CliRunner()
    os.chdir(tmp_path)
    result = runner.invoke(main, [
        "commit", "-c", "No repo", "-t", "result",
    ])
    assert result.exit_code != 0
    assert "Not a resdag repository" in result.output


def test_log_empty(tmp_path):
    runner = CliRunner()
    os.chdir(tmp_path)
    runner.invoke(main, ["init"])
    result = runner.invoke(main, ["log"])
    assert result.exit_code == 0
    assert "No claims yet" in result.output


def test_log_lists_claims(tmp_path):
    runner = CliRunner()
    os.chdir(tmp_path)
    runner.invoke(main, ["init"])
    runner.invoke(main, ["commit", "-c", "Claim A", "-t", "result"])
    runner.invoke(main, ["commit", "-c", "Claim B", "-t", "hypothesis"])
    result = runner.invoke(main, ["log"])
    assert result.exit_code == 0
    assert "Claim A" in result.output
    assert "Claim B" in result.output
    lines = [l for l in result.output.strip().splitlines() if l.strip()]
    assert len(lines) == 2


def test_show_displays_claim(tmp_path):
    runner = CliRunner()
    os.chdir(tmp_path)
    runner.invoke(main, ["init"])
    runner.invoke(main, [
        "commit", "-c", "Test claim", "-t", "method",
        "-d", "inference", "-a", "did:key:abc",
    ])
    # Get CID from log
    log_result = runner.invoke(main, ["log"])
    short_cid = log_result.output.strip().split()[0]
    result = runner.invoke(main, ["show", short_cid])
    assert result.exit_code == 0
    assert "CID:" in result.output
    assert "Type:      method" in result.output
    assert "Claim:     Test claim" in result.output
    assert "Author:    did:key:abc" in result.output
    assert "Domain:    inference" in result.output


def test_show_displays_parents_and_children(tmp_path):
    runner = CliRunner()
    os.chdir(tmp_path)
    runner.invoke(main, ["init"])
    # Create root
    runner.invoke(main, ["commit", "-c", "Root claim", "-t", "result"])
    # Get root CID
    log_result = runner.invoke(main, ["log"])
    root_short = log_result.output.strip().split()[0]
    show_result = runner.invoke(main, ["show", root_short])
    root_cid = [l for l in show_result.output.splitlines() if l.startswith("CID:")][0].split(maxsplit=1)[1].strip()
    # Create child
    runner.invoke(main, [
        "commit", "-c", "Child claim", "-t", "replication", "-p", root_cid,
    ])
    # Show root — should list child
    result = runner.invoke(main, ["show", root_short])
    assert "Children:" in result.output
    assert "Child claim" in result.output
    # Show child — should list parent
    log_result2 = runner.invoke(main, ["log"])
    for line in log_result2.output.strip().splitlines():
        if "Child claim" in line:
            child_short = line.split()[0]
            break
    result2 = runner.invoke(main, ["show", child_short])
    assert "Parents:" in result2.output
    assert "Root claim" in result2.output


def test_show_nonexistent_cid_fails(tmp_path):
    runner = CliRunner()
    os.chdir(tmp_path)
    runner.invoke(main, ["init"])
    result = runner.invoke(main, ["show", "nonexistent"])
    assert result.exit_code != 0
    assert "No claim found" in result.output


def test_log_without_init_fails(tmp_path):
    runner = CliRunner()
    os.chdir(tmp_path)
    result = runner.invoke(main, ["log"])
    assert result.exit_code != 0
    assert "Not a resdag repository" in result.output


def test_show_without_init_fails(tmp_path):
    runner = CliRunner()
    os.chdir(tmp_path)
    result = runner.invoke(main, ["show", "something"])
    assert result.exit_code != 0
    assert "Not a resdag repository" in result.output


def test_roundtrip_init_commit_log_show(tmp_path):
    """Full roundtrip: init -> commit -> log -> show."""
    runner = CliRunner()
    os.chdir(tmp_path)

    # Init
    assert runner.invoke(main, ["init"]).exit_code == 0

    # Commit
    result = runner.invoke(main, [
        "commit", "-c", "Grokking occurs at 10k steps", "-t", "result",
        "-d", "ml.training", "-a", "did:key:z6MkTest",
    ])
    assert result.exit_code == 0

    # Log
    log_result = runner.invoke(main, ["log"])
    assert log_result.exit_code == 0
    assert "Grokking occurs at 10k steps" in log_result.output

    # Show (prefix match)
    short_cid = log_result.output.strip().split()[0]
    show_result = runner.invoke(main, ["show", short_cid])
    assert show_result.exit_code == 0
    assert "ml.training" in show_result.output
    assert "did:key:z6MkTest" in show_result.output


def test_show_displays_verification_status(tmp_path):
    """res show displays verification receipts attached to a claim."""
    runner = CliRunner()
    os.chdir(tmp_path)
    runner.invoke(main, ["init"])

    # Create a result claim
    runner.invoke(main, [
        "commit", "-c", "Chain-of-thought improves GSM8K accuracy by 20%", "-t", "result",
    ])
    log_result = runner.invoke(main, ["log"])
    short_cid = log_result.output.strip().split()[0]
    show_result = runner.invoke(main, ["show", short_cid])
    cid_line = [l for l in show_result.output.splitlines() if l.startswith("CID:")][0]
    full_cid = cid_line.split(maxsplit=1)[1].strip()

    # Create a verification receipt (as a commit with type=verification)
    import json
    payload = json.dumps({
        "description": "Replicated on 500 held-out problems",
        "method": "independent_benchmark",
        "result": "verified",
    }, sort_keys=True)
    runner.invoke(main, [
        "commit", "-c", payload, "-t", "verification", "-p", full_cid,
    ])

    # Show the original claim — should include verification section
    result = runner.invoke(main, ["show", short_cid])
    assert result.exit_code == 0
    assert "Verification:" in result.output
    assert "verified" in result.output
    assert "independent_benchmark" in result.output
    assert "Replicated on 500 held-out problems" in result.output


# --- Log filter tests ---


def _init_and_seed(tmp_path):
    """Init a repo and commit a few claims for filter tests."""
    import os
    runner = CliRunner()
    os.chdir(tmp_path)
    runner.invoke(main, ["init"])
    runner.invoke(main, [
        "commit", "-c", "Grokking at 10k steps", "-t", "result",
        "-d", "ml.training", "-d", "grokking",
        "-T", "2026-03-28T12:00:00Z",
    ])
    runner.invoke(main, [
        "commit", "-c", "Adam converges faster than SGD", "-t", "method",
        "-d", "ml.training",
        "-T", "2026-03-30T08:00:00Z",
    ])
    runner.invoke(main, [
        "commit", "-c", "Grokking is phase transition", "-t", "hypothesis",
        "-d", "grokking", "-d", "physics",
        "-T", "2026-04-01T00:00:00Z",
    ])
    return runner


def test_log_filter_by_domain(tmp_path):
    runner = _init_and_seed(tmp_path)
    result = runner.invoke(main, ["log", "--domain", "grokking"])
    assert result.exit_code == 0
    assert "Grokking at 10k steps" in result.output
    assert "Grokking is phase transition" in result.output
    assert "Adam converges" not in result.output


def test_log_filter_by_type(tmp_path):
    runner = _init_and_seed(tmp_path)
    result = runner.invoke(main, ["log", "--type", "hypothesis"])
    assert result.exit_code == 0
    assert "Grokking is phase transition" in result.output
    assert "Grokking at 10k steps" not in result.output
    assert "Adam converges" not in result.output


def test_log_filter_by_after(tmp_path):
    runner = _init_and_seed(tmp_path)
    result = runner.invoke(main, ["log", "--after", "2026-03-30"])
    assert result.exit_code == 0
    assert "Adam converges" in result.output
    assert "Grokking is phase transition" in result.output
    assert "Grokking at 10k steps" not in result.output


def test_log_filter_by_before(tmp_path):
    runner = _init_and_seed(tmp_path)
    result = runner.invoke(main, ["log", "--before", "2026-03-30"])
    assert result.exit_code == 0
    assert "Grokking at 10k steps" in result.output
    assert "Adam converges" not in result.output
    assert "Grokking is phase transition" not in result.output


def test_log_filters_compose(tmp_path):
    """Filters compose with AND semantics."""
    runner = _init_and_seed(tmp_path)
    result = runner.invoke(main, [
        "log", "--domain", "grokking", "--type", "result",
    ])
    assert result.exit_code == 0
    assert "Grokking at 10k steps" in result.output
    assert "Grokking is phase transition" not in result.output
    assert "Adam converges" not in result.output


def test_log_filters_compose_domain_and_date(tmp_path):
    """Domain + date range filters compose."""
    runner = _init_and_seed(tmp_path)
    result = runner.invoke(main, [
        "log", "--domain", "grokking",
        "--after", "2026-03-29", "--before", "2026-04-02",
    ])
    assert result.exit_code == 0
    assert "Grokking is phase transition" in result.output
    assert "Grokking at 10k steps" not in result.output


def test_log_no_matches(tmp_path):
    runner = _init_and_seed(tmp_path)
    result = runner.invoke(main, ["log", "--domain", "nonexistent"])
    assert result.exit_code == 0
    assert "No claims match" in result.output


# --- Lineage tests ---


def _get_full_cid(runner, short_cid):
    """Resolve a short CID to full CID via res show."""
    show = runner.invoke(main, ["show", short_cid])
    for line in show.output.splitlines():
        if line.startswith("CID:"):
            return line.split(maxsplit=1)[1].strip()
    return None


def _build_chain(tmp_path):
    """Build a 3-node chain: root -> middle -> leaf."""
    import os
    runner = CliRunner()
    os.chdir(tmp_path)
    runner.invoke(main, ["init"])

    runner.invoke(main, [
        "commit", "-c", "Root finding", "-t", "result",
        "-d", "ml", "-T", "2026-03-01T00:00:00Z",
    ])
    log = runner.invoke(main, ["log"])
    root_short = log.output.strip().split()[0]
    root_cid = _get_full_cid(runner, root_short)

    runner.invoke(main, [
        "commit", "-c", "Middle finding", "-t", "result",
        "-p", root_cid, "-d", "ml", "-T", "2026-03-02T00:00:00Z",
    ])
    log = runner.invoke(main, ["log"])
    for line in log.output.strip().splitlines():
        if "Middle" in line:
            mid_short = line.split()[0]
    mid_cid = _get_full_cid(runner, mid_short)

    runner.invoke(main, [
        "commit", "-c", "Leaf finding", "-t", "replication",
        "-p", mid_cid, "-d", "ml", "-T", "2026-03-03T00:00:00Z",
    ])
    log = runner.invoke(main, ["log"])
    for line in log.output.strip().splitlines():
        if "Leaf" in line:
            leaf_short = line.split()[0]

    return runner, root_short, mid_short, leaf_short


def test_lineage_shows_ancestors_and_descendants(tmp_path):
    runner, root_short, mid_short, leaf_short = _build_chain(tmp_path)
    result = runner.invoke(main, ["lineage", mid_short])
    assert result.exit_code == 0
    lines = result.output.strip().splitlines()
    # Root should appear as ancestor (^), middle as focal (*), leaf as descendant (v)
    assert any("^" in l and "Root finding" in l for l in lines)
    assert any("*" in l and "Middle finding" in l for l in lines)
    assert any("v" in l and "Leaf finding" in l for l in lines)


def test_lineage_root_has_no_ancestors(tmp_path):
    runner, root_short, _, _ = _build_chain(tmp_path)
    result = runner.invoke(main, ["lineage", root_short])
    assert result.exit_code == 0
    lines = result.output.strip().splitlines()
    assert any("*" in l and "Root finding" in l for l in lines)
    assert not any(l.lstrip().startswith("^ ") for l in lines)


def test_lineage_leaf_has_no_descendants(tmp_path):
    runner, _, _, leaf_short = _build_chain(tmp_path)
    result = runner.invoke(main, ["lineage", leaf_short])
    assert result.exit_code == 0
    lines = result.output.strip().splitlines()
    assert any("*" in l and "Leaf finding" in l for l in lines)
    # No descendant markers — check for "v " prefix pattern (not just letter v in words)
    assert not any(l.lstrip().startswith("v ") for l in lines)


def test_lineage_shows_indentation(tmp_path):
    runner, _, mid_short, _ = _build_chain(tmp_path)
    result = runner.invoke(main, ["lineage", mid_short])
    lines = result.output.strip().splitlines()
    # Root at depth 0, focal at depth 1, leaf at depth 2
    root_line = [l for l in lines if "Root" in l][0]
    focal_line = [l for l in lines if "Middle" in l][0]
    leaf_line = [l for l in lines if "Leaf" in l][0]
    assert len(root_line) - len(root_line.lstrip()) < len(focal_line) - len(focal_line.lstrip())
    assert len(focal_line) - len(focal_line.lstrip()) < len(leaf_line) - len(leaf_line.lstrip())


def test_lineage_nonexistent_cid_fails(tmp_path):
    import os
    runner = CliRunner()
    os.chdir(tmp_path)
    runner.invoke(main, ["init"])
    result = runner.invoke(main, ["lineage", "nonexistent"])
    assert result.exit_code != 0
    assert "No claim found" in result.output


# --- Orphan and unverified filter tests ---


def test_log_orphans(tmp_path):
    """--orphans shows parentless non-hypothesis claims."""
    import os
    runner = CliRunner()
    os.chdir(tmp_path)
    runner.invoke(main, ["init"])
    # Create a root result (orphan — has no parent)
    runner.invoke(main, ["commit", "-c", "Orphan result", "-t", "result"])
    # Create a hypothesis (parentless by nature)
    runner.invoke(main, ["commit", "-c", "A guess", "-t", "hypothesis"])
    # Get root CID and create a child
    log = runner.invoke(main, ["log"])
    for line in log.output.strip().splitlines():
        if "Orphan result" in line:
            root_short = line.split()[0]
    root_cid = _get_full_cid(runner, root_short)
    runner.invoke(main, [
        "commit", "-c", "Child result", "-t", "result", "-p", root_cid,
    ])

    result = runner.invoke(main, ["log", "--orphans"])
    assert result.exit_code == 0
    assert "Orphan result" in result.output
    # Hypothesis excluded (parentless by nature)
    assert "A guess" not in result.output
    # Child excluded (has parent)
    assert "Child result" not in result.output


def test_log_unverified(tmp_path):
    """--unverified shows claims without verification receipts."""
    import os
    import json
    runner = CliRunner()
    os.chdir(tmp_path)
    runner.invoke(main, ["init"])
    runner.invoke(main, ["commit", "-c", "Verified claim", "-t", "result"])
    runner.invoke(main, ["commit", "-c", "Unverified claim", "-t", "result"])

    # Add a verification receipt to the first claim
    log = runner.invoke(main, ["log"])
    for line in log.output.strip().splitlines():
        if "Verified claim" in line:
            short = line.split()[0]
    full_cid = _get_full_cid(runner, short)
    payload = json.dumps({
        "description": "Checked", "method": "manual", "result": "verified",
    }, sort_keys=True)
    runner.invoke(main, [
        "commit", "-c", payload, "-t", "verification", "-p", full_cid,
    ])

    result = runner.invoke(main, ["log", "--unverified"])
    assert result.exit_code == 0
    assert "Unverified claim" in result.output
    assert "Verified claim" not in result.output


# --- Supersede tests ---


def _setup_supersede(tmp_path):
    """Create two claims, supersede the first with the second."""
    import os
    runner = CliRunner()
    os.chdir(tmp_path)
    runner.invoke(main, ["init"])
    runner.invoke(main, ["commit", "-c", "Old finding", "-t", "result"])
    runner.invoke(main, ["commit", "-c", "Corrected finding", "-t", "result"])

    log = runner.invoke(main, ["log"])
    old_short = new_short = None
    for line in log.output.strip().splitlines():
        if "Old finding" in line:
            old_short = line.split()[0]
        if "Corrected finding" in line:
            new_short = line.split()[0]

    old_cid = _get_full_cid(runner, old_short)
    new_cid = _get_full_cid(runner, new_short)
    return runner, old_short, new_short, old_cid, new_cid


def test_supersede_creates_refutation(tmp_path):
    runner, old_short, new_short, old_cid, new_cid = _setup_supersede(tmp_path)
    result = runner.invoke(main, ["supersede", old_short, new_short])
    assert result.exit_code == 0
    assert "Superseded" in result.output
    assert "Old finding" in result.output
    assert "Corrected finding" in result.output


def test_supersede_with_reason(tmp_path):
    runner, old_short, new_short, _, _ = _setup_supersede(tmp_path)
    result = runner.invoke(main, [
        "supersede", old_short, new_short, "-r", "Parent linking was broken",
    ])
    assert result.exit_code == 0
    assert "Superseded" in result.output


def test_show_displays_supersession(tmp_path):
    runner, old_short, new_short, _, _ = _setup_supersede(tmp_path)
    runner.invoke(main, ["supersede", old_short, new_short, "-r", "Fixed parent links"])
    result = runner.invoke(main, ["show", old_short])
    assert result.exit_code == 0
    assert "SUPERSEDED" in result.output
    assert "Fixed parent links" in result.output


def test_log_active_hides_superseded(tmp_path):
    runner, old_short, new_short, _, _ = _setup_supersede(tmp_path)
    runner.invoke(main, ["supersede", old_short, new_short])

    # Without --active: both claims visible
    log_all = runner.invoke(main, ["log"])
    assert "Old finding" in log_all.output
    assert "Corrected finding" in log_all.output

    # With --active: superseded claim hidden
    log_active = runner.invoke(main, ["log", "--active"])
    assert "Old finding" not in log_active.output
    assert "Corrected finding" in log_active.output


def test_supersede_nonexistent_cid_fails(tmp_path):
    import os
    runner = CliRunner()
    os.chdir(tmp_path)
    runner.invoke(main, ["init"])
    runner.invoke(main, ["commit", "-c", "Some claim", "-t", "result"])
    log = runner.invoke(main, ["log"])
    short = log.output.strip().split()[0]
    result = runner.invoke(main, ["supersede", short, "nonexistent"])
    assert result.exit_code != 0
    assert "No claim found" in result.output


# --- Quick commit (note) tests ---


def test_note_creates_result_claim(tmp_path):
    runner = CliRunner()
    os.chdir(tmp_path)
    runner.invoke(main, ["init"])
    result = runner.invoke(main, ["note", "Grokking happens at 10k steps"])
    assert result.exit_code == 0
    assert "result" in result.output
    assert "Grokking happens at 10k steps" in result.output
    # Verify it appears in log
    log = runner.invoke(main, ["log"])
    assert "Grokking happens at 10k steps" in log.output


def test_note_with_domain_and_parent(tmp_path):
    runner = CliRunner()
    os.chdir(tmp_path)
    runner.invoke(main, ["init"])
    runner.invoke(main, ["note", "Root claim"])
    log = runner.invoke(main, ["log"])
    short = log.output.strip().split()[0]
    result = runner.invoke(main, [
        "note", "Follow-up claim", "-d", "ml", "-p", short,
    ])
    assert result.exit_code == 0
    assert "result" in result.output


# --- Ingest tests ---


def test_ingest_single_object(tmp_path):
    import json
    runner = CliRunner()
    os.chdir(tmp_path)
    runner.invoke(main, ["init"])
    data = {"accuracy": 95.2, "steps": 10000}
    (tmp_path / "results.json").write_text(json.dumps(data))
    result = runner.invoke(main, [
        "ingest", "results.json",
        "-t", "Accuracy: {accuracy}% at {steps} steps",
        "-d", "ml",
    ])
    assert result.exit_code == 0
    assert "Accuracy: 95.2% at 10000 steps" in result.output
    assert "Ingested 1 claim" in result.output
    # Verify in log
    log = runner.invoke(main, ["log"])
    assert "Accuracy: 95.2%" in log.output


def test_ingest_array(tmp_path):
    import json
    runner = CliRunner()
    os.chdir(tmp_path)
    runner.invoke(main, ["init"])
    data = [
        {"epoch": 1, "loss": 0.5},
        {"epoch": 2, "loss": 0.3},
        {"epoch": 3, "loss": 0.1},
    ]
    (tmp_path / "training.json").write_text(json.dumps(data))
    result = runner.invoke(main, [
        "ingest", "training.json",
        "-t", "Epoch {epoch}: loss={loss}",
    ])
    assert result.exit_code == 0
    assert "Ingested 3 claim" in result.output
    assert "Epoch 1: loss=0.5" in result.output
    assert "Epoch 3: loss=0.1" in result.output


def test_ingest_no_template_uses_json(tmp_path):
    import json
    runner = CliRunner()
    os.chdir(tmp_path)
    runner.invoke(main, ["init"])
    data = {"metric": "f1", "value": 0.92}
    (tmp_path / "result.json").write_text(json.dumps(data))
    result = runner.invoke(main, ["ingest", "result.json"])
    assert result.exit_code == 0
    assert "Ingested 1 claim" in result.output


def test_ingest_attaches_evidence(tmp_path):
    import json
    runner = CliRunner()
    os.chdir(tmp_path)
    runner.invoke(main, ["init"])
    data = {"accuracy": 99}
    (tmp_path / "r.json").write_text(json.dumps(data))
    runner.invoke(main, ["ingest", "r.json", "-t", "Acc: {accuracy}%"])
    # Check that evidence is attached via show
    log = runner.invoke(main, ["log"])
    short = log.output.strip().splitlines()[0].split()[0]
    show = runner.invoke(main, ["show", short])
    assert "Evidence:" in show.output
    assert "r.json" in show.output

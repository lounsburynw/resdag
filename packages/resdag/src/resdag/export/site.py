"""Static site generator.

Generates a static HTML website from a local DAG. Each claim becomes a
page with parent/child navigation, domain tags, verification status, and
equivalence cluster links. Deployable to GitHub Pages or any static host.
"""

from __future__ import annotations

from pathlib import Path

from jinja2 import Environment

from resdag.claim import ClaimType
from resdag.dag import ClaimStore, DAG
from resdag.discover.equivalence import equivalence_cluster
from resdag.verify.receipt import parse_receipt, verification_status

# ── Templates ────────────────────────────────────────────────────

_CSS = """\
body { font-family: system-ui, sans-serif; max-width: 50rem; margin: 2rem auto; padding: 0 1rem; color: #1a1a1a; }
a { color: #0066cc; text-decoration: none; }
a:hover { text-decoration: underline; }
h1 { font-size: 1.5rem; border-bottom: 2px solid #eee; padding-bottom: 0.5rem; }
h2 { font-size: 1.1rem; margin-top: 1.5rem; color: #555; }
.claim-type { display: inline-block; padding: 0.15rem 0.5rem; border-radius: 3px; font-size: 0.8rem; font-weight: 600; text-transform: uppercase; }
.type-result { background: #d4edda; color: #155724; }
.type-method { background: #d1ecf1; color: #0c5460; }
.type-hypothesis { background: #fff3cd; color: #856404; }
.type-replication { background: #cce5ff; color: #004085; }
.type-equivalence { background: #e2d9f3; color: #432874; }
.type-refutation { background: #f8d7da; color: #721c24; }
.type-verification { background: #d6d8db; color: #383d41; }
.tag { display: inline-block; padding: 0.1rem 0.4rem; margin: 0.1rem; background: #f0f0f0; border-radius: 3px; font-size: 0.8rem; }
.meta { color: #666; font-size: 0.85rem; }
.cid { font-family: monospace; font-size: 0.8rem; }
ul { list-style: none; padding-left: 0; }
li { margin: 0.3rem 0; }
.claim-list li { padding: 0.4rem 0; border-bottom: 1px solid #f0f0f0; }
.verification { margin: 0.3rem 0; padding: 0.3rem 0.5rem; background: #f8f9fa; border-radius: 3px; font-size: 0.9rem; }
.ver-verified { border-left: 3px solid #28a745; }
.ver-unverified { border-left: 3px solid #dc3545; }
.ver-partial { border-left: 3px solid #ffc107; }
nav { margin-bottom: 1.5rem; }
"""

_INDEX_TEMPLATE = """\
<!DOCTYPE html>
<html lang="en">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>ResDAG</title><style>{{ css }}</style></head>
<body>
<h1>ResDAG</h1>
<p class="meta">{{ total }} claim{{ "s" if total != 1 else "" }}</p>
{% if domains %}
<h2>Domains</h2>
<ul>
{% for domain in domains %}
<li><a href="domains/{{ domain }}.html">{{ domain }}</a></li>
{% endfor %}
</ul>
{% endif %}
<h2>All Claims</h2>
<ul class="claim-list">
{% for cid, claim in claims %}
<li>
<span class="claim-type type-{{ claim.type.value }}">{{ claim.type.value }}</span>
<a href="claims/{{ cid }}.html">{{ claim.claim }}</a>
<span class="meta">{{ claim.timestamp[:10] }}</span>
</li>
{% endfor %}
</ul>
</body>
</html>
"""

_CLAIM_TEMPLATE = """\
<!DOCTYPE html>
<html lang="en">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{{ claim.claim }}</title><style>{{ css }}</style></head>
<body>
<nav><a href="../index.html">&larr; Index</a></nav>
<h1>{{ claim.claim }}</h1>
<p><span class="claim-type type-{{ claim.type.value }}">{{ claim.type.value }}</span></p>
<p class="meta">
CID: <span class="cid">{{ cid }}</span><br>
Author: {{ claim.author or "(anonymous)" }}<br>
Timestamp: {{ claim.timestamp }}
</p>
{% if claim.domain %}
<p>{% for d in claim.domain %}<span class="tag">{{ d }}</span>{% endfor %}</p>
{% endif %}
{% if parents %}
<h2>Parents</h2>
<ul>
{% for pcid, pclaim in parents %}
<li><span class="claim-type type-{{ pclaim.type.value }}">{{ pclaim.type.value }}</span> <a href="{{ pcid }}.html">{{ pclaim.claim }}</a></li>
{% endfor %}
</ul>
{% endif %}
{% if children %}
<h2>Children</h2>
<ul>
{% for ccid, cclaim in children %}
<li><span class="claim-type type-{{ cclaim.type.value }}">{{ cclaim.type.value }}</span> <a href="{{ ccid }}.html">{{ cclaim.claim }}</a></li>
{% endfor %}
</ul>
{% endif %}
{% if receipts %}
<h2>Verification</h2>
{% for r in receipts %}
<div class="verification ver-{{ r.result.value }}">
<strong>{{ r.result.value }}</strong> &mdash; {{ r.method }}{% if r.confidence is not none %} (confidence: {{ r.confidence }}){% endif %}
{% if r.description %}<br><span class="meta">{{ r.description }}</span>{% endif %}
</div>
{% endfor %}
{% endif %}
{% if equivalents %}
<h2>Equivalent Claims</h2>
<ul>
{% for ecid, eclaim in equivalents %}
<li><a href="{{ ecid }}.html">{{ eclaim.claim }}</a></li>
{% endfor %}
</ul>
{% endif %}
{% if claim.evidence %}
<h2>Evidence</h2>
<ul>
{% for ev in evidence_info %}
<li><span class="cid">{{ ev.cid[:12] }}</span> {{ ev.filename }} <span class="meta">({{ ev.media_type }}, {{ ev.size }} bytes)</span></li>
{% endfor %}
</ul>
{% endif %}
{% if claim.signature %}
<p class="meta">Signature: <span class="cid">{{ claim.signature[:24] }}...</span></p>
{% endif %}
</body>
</html>
"""

_DOMAIN_TEMPLATE = """\
<!DOCTYPE html>
<html lang="en">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{{ domain }} — ResDAG</title><style>{{ css }}</style></head>
<body>
<nav><a href="../index.html">&larr; Index</a></nav>
<h1>{{ domain }}</h1>
<ul class="claim-list">
{% for cid, claim in claims %}
<li>
<span class="claim-type type-{{ claim.type.value }}">{{ claim.type.value }}</span>
<a href="../claims/{{ cid }}.html">{{ claim.claim }}</a>
<span class="meta">{{ claim.timestamp[:10] }}</span>
</li>
{% endfor %}
</ul>
</body>
</html>
"""

# ── Evidence info helper ─────────────────────────────────────────


class _EvidenceInfo:
    """Lightweight container for evidence metadata in templates."""

    __slots__ = ("cid", "filename", "media_type", "size")

    def __init__(self, cid: str, filename: str, media_type: str, size: int) -> None:
        self.cid = cid
        self.filename = filename
        self.media_type = media_type
        self.size = size


# ── Public API ───────────────────────────────────────────────────


def generate_site(store: ClaimStore, output_dir: str | Path) -> int:
    """Generate a static HTML site from all claims in the store.

    Creates index.html, claims/{cid}.html for each claim, and
    domains/{tag}.html for each domain tag.

    Returns the number of claim pages generated.
    """
    output = Path(output_dir)
    claims_dir = output / "claims"
    domains_dir = output / "domains"
    claims_dir.mkdir(parents=True, exist_ok=True)
    domains_dir.mkdir(parents=True, exist_ok=True)

    dag = DAG(store)
    env = Environment(autoescape=True)

    all_cids = store.list_cids()
    all_claims = [(cid, store.get(cid)) for cid in all_cids]
    # Sort by timestamp descending (newest first)
    all_claims.sort(key=lambda x: x[1].timestamp, reverse=True)

    # Collect all domain tags
    domain_set: set[str] = set()
    for _, claim in all_claims:
        domain_set.update(claim.domain)

    # ── Index page ───────────────────────────────────────────
    index_html = env.from_string(_INDEX_TEMPLATE).render(
        css=_CSS,
        total=len(all_claims),
        domains=sorted(domain_set),
        claims=all_claims,
    )
    (output / "index.html").write_text(index_html)

    # ── Claim pages ──────────────────────────────────────────
    children_map = dag._children_map()
    for cid, claim in all_claims:
        parents = [(p, store.get(p)) for p in claim.parents if store.has(p)]
        children = [
            (c, store.get(c)) for c in children_map.get(cid, [])
        ]

        # Verification receipts (skip for verification claims themselves)
        receipts = []
        if claim.type != ClaimType.VERIFICATION:
            receipts = verification_status(cid, dag)

        # Equivalence cluster (skip for equivalence claims)
        equivalents = []
        if claim.type != ClaimType.EQUIVALENCE:
            cluster = equivalence_cluster(cid, dag)
            cluster.discard(cid)
            equivalents = [
                (ecid, store.get(ecid)) for ecid in sorted(cluster)
            ]

        # Evidence metadata
        evidence_info = []
        for ev_cid in claim.evidence:
            if hasattr(store, "get_evidence_meta"):
                meta = store.get_evidence_meta(ev_cid)
                if meta:
                    evidence_info.append(_EvidenceInfo(
                        cid=ev_cid,
                        filename=meta.get("filename", ""),
                        media_type=meta.get("media_type", ""),
                        size=meta.get("size", 0),
                    ))
                else:
                    evidence_info.append(_EvidenceInfo(
                        cid=ev_cid, filename="", media_type="", size=0,
                    ))

        claim_html = env.from_string(_CLAIM_TEMPLATE).render(
            css=_CSS,
            cid=cid,
            claim=claim,
            parents=parents,
            children=children,
            receipts=receipts,
            equivalents=equivalents,
            evidence_info=evidence_info,
        )
        (claims_dir / f"{cid}.html").write_text(claim_html)

    # ── Domain pages ─────────────────────────────────────────
    for domain in sorted(domain_set):
        domain_claims = [
            (cid, claim)
            for cid, claim in all_claims
            if domain in claim.domain
        ]
        domain_html = env.from_string(_DOMAIN_TEMPLATE).render(
            css=_CSS,
            domain=domain,
            claims=domain_claims,
        )
        (domains_dir / f"{domain}.html").write_text(domain_html)

    return len(all_claims)

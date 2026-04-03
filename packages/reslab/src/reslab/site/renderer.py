"""Generate a browsable static site from a resdag store."""

from __future__ import annotations

import json
from pathlib import Path

from jinja2 import Environment, BaseLoader
from markupsafe import Markup

from resdag.dag import DAG
from resdag.storage.local import LocalStore

from reslab.audit import audit_dag
from reslab.site.structured import (
    ParsedClaim,
    parse_sections,
    infer_implicit_threads,
)
from reslab.threads import discover_threads
from reslab.vocabulary import Vocabulary, load_vocabulary


def generate_site(store: LocalStore, output_dir: str | Path) -> int:
    """Render a static site from a resdag store.

    Returns the number of claims rendered.
    """
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    (output / "claims").mkdir(exist_ok=True)

    dag = DAG(store)
    cids = store.list_cids()
    vocab = load_vocabulary(store.root)
    claims_data = _build_claims_data(store, dag, cids, vocab)
    graph_data = _build_graph_data(store, dag, cids, vocab)
    health = audit_dag(store).to_dict() if cids else None

    # Infer implicit threads from linear chains
    implicit_threads = infer_implicit_threads(store)
    implicit_threads_data = [
        {
            "root_cid": t.root_cid,
            "root_short_cid": t.root_cid[:12],
            "root_text": t.root_text,
            "count": len(t.cids),
            "domains": t.domains,
            "first_date": t.first_date[:10] if t.first_date else "",
            "last_date": t.last_date[:10] if t.last_date else "",
            "cids": t.cids,
        }
        for t in implicit_threads
    ]

    # Build lookup: CID → list of implicit thread indices (for claim detail nav)
    cid_to_implicit_threads: dict[str, list[int]] = {}
    for idx, t in enumerate(implicit_threads_data):
        for c in t["cids"]:
            cid_to_implicit_threads.setdefault(c, []).append(idx)

    # Annotate claims with implicit thread membership
    for claim_info in claims_data:
        thread_indices = cid_to_implicit_threads.get(claim_info["cid"], [])
        claim_info["implicit_threads"] = [implicit_threads_data[i] for i in thread_indices]

    env = Environment(loader=BaseLoader(), autoescape=True)

    # Render index — use canonical tags for filter bar when vocabulary exists
    index_tmpl = env.from_string(_INDEX_TEMPLATE)
    all_data_domains = {d for c in claims_data for d in c["domains"]}
    if vocab is not None:
        domains = sorted(d for d in vocab.canonical_tags() if d in all_data_domains)
    else:
        domains = sorted(all_data_domains)
    types = sorted({c["type"] for c in claims_data})
    (output / "index.html").write_text(
        index_tmpl.render(
            claims=claims_data,
            domains=domains,
            types=types,
            graph_json=Markup(json.dumps(graph_data)),
            count=len(claims_data),
            health=health,
            implicit_threads=implicit_threads_data,
        )
    )

    # Render individual claim pages
    claim_tmpl = env.from_string(_CLAIM_TEMPLATE)
    for claim_info in claims_data:
        (output / "claims" / f"{claim_info['cid']}.html").write_text(
            claim_tmpl.render(claim=claim_info)
        )

    # Render thread pages
    threads = discover_threads(store)
    if threads:
        (output / "threads").mkdir(exist_ok=True)

        # Build a lookup from CID to claims_data entry for thread detail pages
        claims_by_cid = {c["cid"]: c for c in claims_data}

        threads_data = []
        for t in threads:
            thread_claims = []
            h_data = claims_by_cid.get(t.hypothesis_cid)
            if h_data:
                thread_claims.append(h_data)
            for d_cid in t.descendant_cids:
                if d_cid in claims_by_cid:
                    thread_claims.append(claims_by_cid[d_cid])
            # Sort thread claims by timestamp (oldest first for narrative order)
            thread_claims.sort(key=lambda c: c["timestamp"])

            td = {
                "hypothesis_cid": t.hypothesis_cid,
                "hypothesis_short_cid": t.hypothesis_cid[:12],
                "hypothesis_text": t.hypothesis_text,
                "status": t.status,
                "status_icon": {"open": "○", "confirmed": "✓", "refuted": "✗", "mixed": "◐"}.get(t.status, "?"),
                "claim_count": t.claim_count,
                "domains": t.domains,
                "first_date": t.first_date[:10] if t.first_date else "",
                "last_date": t.last_date[:10] if t.last_date else "",
                "claims": thread_claims,
            }
            threads_data.append(td)

        # Thread index
        thread_index_tmpl = env.from_string(_THREAD_INDEX_TEMPLATE)
        (output / "threads" / "index.html").write_text(
            thread_index_tmpl.render(threads=threads_data, count=len(threads_data))
        )

        # Per-thread detail pages
        thread_detail_tmpl = env.from_string(_THREAD_DETAIL_TEMPLATE)
        for td in threads_data:
            (output / "threads" / f"{td['hypothesis_cid']}.html").write_text(
                thread_detail_tmpl.render(thread=td)
            )

    return len(claims_data)


def _normalize_domains(domains: tuple[str, ...], vocab: Vocabulary | None) -> list[str]:
    """Normalize domains through vocabulary if available."""
    if vocab is None:
        return list(domains)
    normalized, _ = vocab.normalize(domains)
    return normalized


def _build_claims_data(store: LocalStore, dag: DAG, cids: list[str], vocab: Vocabulary | None = None) -> list[dict]:
    """Build template-ready claim data sorted by timestamp descending."""
    children_map: dict[str, list[str]] = {}
    for cid in cids:
        claim = store.get(cid)
        for parent in claim.parents:
            children_map.setdefault(parent, []).append(cid)

    claims = []
    for cid in cids:
        claim = store.get(cid)

        # Resolve parent/child summaries
        parents = []
        for pcid in claim.parents:
            if store.has(pcid):
                p = store.get(pcid)
                parents.append({"cid": pcid, "short_cid": pcid[:12], "type": p.type.value, "text": p.claim})

        children = []
        for ccid in children_map.get(cid, []):
            c = store.get(ccid)
            children.append({"cid": ccid, "short_cid": ccid[:12], "type": c.type.value, "text": c.claim})

        # Evidence metadata
        evidence = []
        for ecid in claim.evidence:
            meta = {}
            if store.has_evidence(ecid):
                try:
                    meta = store.get_evidence_meta(ecid)
                except Exception:
                    pass
            evidence.append({
                "cid": ecid,
                "short_cid": ecid[:12],
                "filename": meta.get("filename", "unknown"),
                "media_type": meta.get("media_type", "application/octet-stream"),
                "size": meta.get("size", 0),
            })

        parsed = parse_sections(claim.claim, claim.type.value)

        claims.append({
            "cid": cid,
            "short_cid": cid[:12],
            "text": claim.claim,
            "type": claim.type.value,
            "domains": _normalize_domains(claim.domain, vocab),
            "timestamp": claim.timestamp,
            "date": claim.timestamp[:10] if claim.timestamp else "",
            "author": claim.author or "(anonymous)",
            "parents": parents,
            "children": children,
            "evidence": evidence,
            # Structured rendering fields
            "is_structured": parsed.is_structured,
            "sections": parsed.sections,
            "title": parsed.title,
            "body": parsed.body,
            "summary": parsed.summary,
        })

    claims.sort(key=lambda c: c["timestamp"], reverse=True)
    return claims


def _build_graph_data(store: LocalStore, dag: DAG, cids: list[str], vocab: Vocabulary | None = None) -> dict:
    """Build D3-compatible graph JSON (nodes + links)."""
    nodes = []
    links = []

    for cid in cids:
        claim = store.get(cid)
        nodes.append({
            "id": cid,
            "short_cid": cid[:12],
            "label": claim.claim[:80],
            "type": claim.type.value,
            "domains": _normalize_domains(claim.domain, vocab),
            "date": claim.timestamp[:10] if claim.timestamp else "",
        })
        for parent_cid in claim.parents:
            links.append({"source": parent_cid, "target": cid})

    return {"nodes": nodes, "links": links}


# ---------------------------------------------------------------------------
# Templates
# ---------------------------------------------------------------------------

_CSS = """\
:root {
  --bg: #0d1117; --fg: #e6edf3; --muted: #8b949e; --border: #30363d;
  --card: #161b22; --link: #58a6ff;
  --result: #238636; --method: #1f6feb; --hypothesis: #d29922;
  --replication: #58a6ff; --refutation: #f85149; --verification: #8b949e;
  --equivalence: #a371f7;
}
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
  background: var(--bg); color: var(--fg); line-height: 1.6; }
a { color: var(--link); text-decoration: none; }
a:hover { text-decoration: underline; }

.container { max-width: 72rem; margin: 0 auto; padding: 2rem; }
header { display: flex; justify-content: space-between; align-items: center;
  border-bottom: 1px solid var(--border); padding-bottom: 1rem; margin-bottom: 2rem; }
header h1 { font-size: 1.5rem; font-weight: 600; }
.meta { color: var(--muted); font-size: 0.875rem; }

/* Filters */
.filters { display: flex; gap: 0.5rem; flex-wrap: wrap; margin-bottom: 1.5rem; }
.filter-btn { background: var(--card); border: 1px solid var(--border); color: var(--fg);
  padding: 0.25rem 0.75rem; border-radius: 1rem; cursor: pointer; font-size: 0.8rem; }
.filter-btn:hover, .filter-btn.active { border-color: var(--link); color: var(--link); }
.active-chips { display: flex; gap: 0.5rem; flex-wrap: wrap; margin-bottom: 1rem; }
.chip { display: inline-flex; align-items: center; gap: 0.25rem; background: var(--link);
  color: #fff; padding: 0.2rem 0.6rem; border-radius: 1rem; font-size: 0.75rem; cursor: pointer; }
.chip:hover { opacity: 0.8; }
.chip .chip-x { font-weight: 700; margin-left: 0.15rem; }

/* DAG */
#dag-container { width: 100%; height: 400px; border: 1px solid var(--border);
  border-radius: 0.5rem; margin-bottom: 2rem; background: var(--card); }
#dag-container svg { width: 100%; height: 100%; }

/* Claims list */
.claim-card { background: var(--card); border: 1px solid var(--border); border-radius: 0.5rem;
  padding: 1rem; margin-bottom: 0.75rem; border-left: 3px solid var(--border); }
.claim-card[data-type="result"] { border-left-color: var(--result); }
.claim-card[data-type="method"] { border-left-color: var(--method); }
.claim-card[data-type="hypothesis"] { border-left-color: var(--hypothesis); }
.claim-card[data-type="replication"] { border-left-color: var(--replication); }
.claim-card[data-type="refutation"] { border-left-color: var(--refutation); }
.claim-card[data-type="verification"] { border-left-color: var(--verification); }
.claim-card[data-type="equivalence"] { border-left-color: var(--equivalence); }

.badge { display: inline-block; padding: 0.1rem 0.5rem; border-radius: 0.75rem;
  font-size: 0.7rem; font-weight: 600; text-transform: uppercase; }
.badge-result { background: var(--result); color: #fff; }
.badge-method { background: var(--method); color: #fff; }
.badge-hypothesis { background: var(--hypothesis); color: #000; }
.badge-replication { background: var(--replication); color: #000; }
.badge-refutation { background: var(--refutation); color: #fff; }
.badge-verification { background: var(--verification); color: #fff; }
.badge-equivalence { background: var(--equivalence); color: #fff; }

.claim-text { margin: 0.5rem 0; }
.claim-meta { display: flex; gap: 1rem; color: var(--muted); font-size: 0.8rem; }
.domain-tag { background: var(--border); padding: 0.1rem 0.4rem; border-radius: 0.25rem;
  font-size: 0.75rem; }

/* Claim detail page */
.detail-section { margin-bottom: 1.5rem; }
.detail-section h2 { font-size: 1.1rem; color: var(--muted); margin-bottom: 0.5rem;
  text-transform: uppercase; letter-spacing: 0.05em; font-weight: 500; }
.lineage-item { padding: 0.5rem; background: var(--card); border-radius: 0.25rem;
  margin-bottom: 0.25rem; }
.cid { font-family: ui-monospace, monospace; font-size: 0.8rem; color: var(--muted); }
.hidden { display: none; }

/* Health badge */
.health-badge { display: flex; gap: 1rem; flex-wrap: wrap; padding: 0.75rem 1rem;
  background: var(--card); border: 1px solid var(--border); border-radius: 0.5rem;
  margin-bottom: 1.5rem; font-size: 0.8rem; color: var(--muted); }
.health-stat { display: flex; flex-direction: column; align-items: center; }
.health-val { font-size: 1.1rem; font-weight: 600; color: var(--fg); }
.health-warn { color: var(--refutation); }
"""

_DAG_JS = """\
function renderDAG(graphData, container) {
  if (!graphData.nodes.length) return;

  const width = container.clientWidth;
  const height = container.clientHeight;

  const typeColors = {
    result: '#238636', method: '#1f6feb', hypothesis: '#d29922',
    replication: '#58a6ff', refutation: '#f85149', verification: '#8b949e',
    equivalence: '#a371f7'
  };

  const svg = d3.select(container).append('svg')
    .attr('viewBox', [0, 0, width, height]);

  // Arrow marker
  svg.append('defs').append('marker')
    .attr('id', 'arrow').attr('viewBox', '0 -5 10 10')
    .attr('refX', 20).attr('refY', 0)
    .attr('markerWidth', 6).attr('markerHeight', 6)
    .attr('orient', 'auto')
    .append('path').attr('d', 'M0,-5L10,0L0,5').attr('fill', '#30363d');

  const simulation = d3.forceSimulation(graphData.nodes)
    .force('link', d3.forceLink(graphData.links).id(d => d.id).distance(80))
    .force('charge', d3.forceManyBody().strength(-200))
    .force('center', d3.forceCenter(width / 2, height / 2))
    .force('y', d3.forceY(height / 2).strength(0.05));

  const link = svg.append('g').selectAll('line')
    .data(graphData.links).join('line')
    .attr('stroke', '#30363d').attr('stroke-width', 1.5)
    .attr('marker-end', 'url(#arrow)');

  const node = svg.append('g').selectAll('g')
    .data(graphData.nodes).join('g')
    .call(d3.drag()
      .on('start', (e, d) => { if (!e.active) simulation.alphaTarget(0.3).restart(); d.fx = e.x; d.fy = e.y; })
      .on('drag', (e, d) => { d.fx = e.x; d.fy = e.y; })
      .on('end', (e, d) => { if (!e.active) simulation.alphaTarget(0); d.fx = null; d.fy = null; })
    );

  node.append('circle')
    .attr('r', 8)
    .attr('fill', d => typeColors[d.type] || '#8b949e')
    .attr('stroke', '#e6edf3').attr('stroke-width', 1.5);

  node.append('title').text(d => d.label);

  // Click to navigate
  node.style('cursor', 'pointer')
    .on('click', (e, d) => { window.location.href = 'claims/' + d.id + '.html'; });

  simulation.on('tick', () => {
    link.attr('x1', d => d.source.x).attr('y1', d => d.source.y)
        .attr('x2', d => d.target.x).attr('y2', d => d.target.y);
    node.attr('transform', d => `translate(${d.x},${d.y})`);
  });

  // Expose for filtering
  container._nodes = node;
  container._links = link;
  container._simulation = simulation;
}
"""

_FILTER_JS = """\
function initFilters(graphData) {
  const cards = document.querySelectorAll('.claim-card');
  const typeButtons = document.querySelectorAll('.filter-btn[data-type]');
  const domainButtons = document.querySelectorAll('.filter-btn[data-domain]');
  const chipContainer = document.getElementById('active-chips');
  let activeType = null;
  const activeDomains = new Set();

  function renderChips() {
    if (!chipContainer) return;
    chipContainer.innerHTML = '';
    if (activeType) {
      const chip = document.createElement('span');
      chip.className = 'chip';
      chip.innerHTML = 'type: ' + activeType + ' <span class="chip-x">&times;</span>';
      chip.addEventListener('click', () => { removeType(); });
      chipContainer.appendChild(chip);
    }
    activeDomains.forEach(d => {
      const chip = document.createElement('span');
      chip.className = 'chip';
      chip.innerHTML = d + ' <span class="chip-x">&times;</span>';
      chip.addEventListener('click', () => { removeDomain(d); });
      chipContainer.appendChild(chip);
    });
  }

  function removeType() {
    activeType = null;
    typeButtons.forEach(b => b.classList.remove('active'));
    applyFilters();
  }

  function removeDomain(d) {
    activeDomains.delete(d);
    domainButtons.forEach(b => {
      if (b.dataset.domain === d) b.classList.remove('active');
    });
    applyFilters();
  }

  function applyFilters() {
    cards.forEach(card => {
      const matchType = !activeType || card.dataset.type === activeType;
      let matchDomain = true;
      if (activeDomains.size > 0) {
        const cardDomains = (card.dataset.domains || '').split(',');
        for (const d of activeDomains) {
          if (!cardDomains.includes(d)) { matchDomain = false; break; }
        }
      }
      card.classList.toggle('hidden', !(matchType && matchDomain));
    });
    const visible = document.querySelectorAll('.claim-card:not(.hidden)').length;
    const counter = document.getElementById('visible-count');
    if (counter) counter.textContent = visible + ' of ' + cards.length;
    renderChips();
  }

  typeButtons.forEach(btn => {
    btn.addEventListener('click', () => {
      const t = btn.dataset.type;
      activeType = activeType === t ? null : t;
      typeButtons.forEach(b => b.classList.toggle('active', b.dataset.type === activeType));
      applyFilters();
    });
  });

  domainButtons.forEach(btn => {
    btn.addEventListener('click', () => {
      const d = btn.dataset.domain;
      if (activeDomains.has(d)) { activeDomains.delete(d); } else { activeDomains.add(d); }
      btn.classList.toggle('active');
      applyFilters();
    });
  });
}
"""

_INDEX_TEMPLATE = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Research DAG</title>
<style>""" + _CSS + """</style>
<script src="https://d3js.org/d3.v7.min.js"></script>
</head>
<body>
<div class="container">
  <header>
    <h1>Research DAG</h1>
    <span class="meta"><a href="threads/index.html">Threads</a> &middot; <span id="visible-count">{{ count }} of {{ count }}</span></span>
  </header>

  {% if health %}
  <div class="health-badge">
    <div class="health-stat"><span class="health-val">{{ health.hypothesis_count }}</span>hypotheses</div>
    <div class="health-stat"><span class="health-val">{{ (health.hypothesis_coverage * 100) | int }}%</span>coverage</div>
    <div class="health-stat"><span class="health-val {% if health.orphan_rate > 0.3 %}health-warn{% endif %}">{{ (health.orphan_rate * 100) | int }}%</span>orphans</div>
    <div class="health-stat"><span class="health-val">{{ (health.branch_ratio * 100) | int }}%</span>branching</div>
    <div class="health-stat"><span class="health-val {% if health.max_linear_run > 10 %}health-warn{% endif %}">{{ health.max_linear_run }}</span>max run</div>
    <div class="health-stat"><span class="health-val">{{ health.refutation_count }}</span>refutations</div>
  </div>
  {% endif %}

  <div id="dag-container"></div>

  <div class="filters">
    <strong style="color:var(--muted);font-size:0.8rem;line-height:2">Type:</strong>
    {% for t in types %}
    <button class="filter-btn" data-type="{{ t }}">{{ t }}</button>
    {% endfor %}
  </div>
  {% if domains %}
  <div class="filters">
    <strong style="color:var(--muted);font-size:0.8rem;line-height:2">Domain:</strong>
    {% for d in domains %}
    <button class="filter-btn" data-domain="{{ d }}">{{ d }}</button>
    {% endfor %}
  </div>
  {% endif %}
  <div id="active-chips" class="active-chips"></div>

  {% if implicit_threads %}
  <div class="detail-section" style="margin-bottom:1.5rem">
    <h2 style="font-size:1rem;color:var(--muted);margin-bottom:0.5rem">Implicit Threads</h2>
    {% for t in implicit_threads %}
    <div class="thread-card" data-status="open" style="background:var(--card);border:1px solid var(--border);border-radius:0.5rem;padding:0.75rem;margin-bottom:0.5rem;border-left:3px solid var(--muted)">
      <div class="claim-text"><a href="claims/{{ t.root_cid }}.html">{{ t.root_text }}</a></div>
      <div class="claim-meta">
        <span class="cid">{{ t.root_short_cid }}</span>
        <span>{{ t.count }} claims</span>
        <span>{{ t.first_date }}–{{ t.last_date }}</span>
        {% for d in t.domains %}<span class="domain-tag">{{ d }}</span>{% endfor %}
      </div>
    </div>
    {% endfor %}
  </div>
  {% endif %}

  <div id="claims-list">
    {% for c in claims %}
    <div class="claim-card" data-type="{{ c.type }}" data-domains="{{ c.domains | join(',') }}">
      <span class="badge badge-{{ c.type }}">{{ c.type }}</span>
      {% if c.title %}<div class="claim-title" style="font-size:0.85rem;color:var(--muted);margin-top:0.25rem">{{ c.title }}</div>{% endif %}
      <div class="claim-text"><a href="claims/{{ c.cid }}.html">{{ c.summary or c.text }}</a></div>
      <div class="claim-meta">
        <span class="cid">{{ c.short_cid }}</span>
        <span>{{ c.date }}</span>
        {% for d in c.domains %}<span class="domain-tag">{{ d }}</span>{% endfor %}
      </div>
    </div>
    {% endfor %}
  </div>
</div>

<script>""" + _DAG_JS + """</script>
<script>""" + _FILTER_JS + """</script>
<script>
  const graphData = {{ graph_json }};
  renderDAG(graphData, document.getElementById('dag-container'));
  initFilters(graphData);
</script>
</body>
</html>
"""

_STRUCTURED_CSS = """\
.section-block { margin-bottom: 1rem; padding: 0.75rem 1rem; background: var(--card);
  border: 1px solid var(--border); border-radius: 0.5rem; }
.section-label { font-size: 0.75rem; font-weight: 600; text-transform: uppercase;
  letter-spacing: 0.05em; color: var(--muted); margin-bottom: 0.25rem; }
.section-text { white-space: pre-wrap; }
.implicit-thread-nav { display: flex; gap: 0.5rem; flex-wrap: wrap;
  padding: 0.5rem 0; margin-bottom: 1rem; }
.implicit-thread-link { background: var(--card); border: 1px solid var(--border);
  padding: 0.25rem 0.75rem; border-radius: 1rem; font-size: 0.8rem; color: var(--link); }
"""

_CLAIM_TEMPLATE = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{{ claim.summary or claim.text[:60] }}</title>
<style>""" + _CSS + _STRUCTURED_CSS + """</style>
</head>
<body>
<div class="container">
  <p><a href="../index.html">&larr; Back</a></p>

  <header>
    {% if claim.is_structured %}
    <h1>{{ claim.summary }}</h1>
    {% elif claim.title %}
    <h1>{{ claim.title }}</h1>
    {% else %}
    <h1>{{ claim.text }}</h1>
    {% endif %}
    <span class="badge badge-{{ claim.type }}">{{ claim.type }}</span>
  </header>

  {% if claim.implicit_threads %}
  <div class="implicit-thread-nav">
    {% for t in claim.implicit_threads %}
    <a class="implicit-thread-link" href="{{ t.root_cid }}.html" title="Thread: {{ t.root_text }}">&#x1f517; {{ t.count }} claims &middot; {{ t.domains | join(', ') }}</a>
    {% endfor %}
  </div>
  {% endif %}

  {% if claim.is_structured %}
  <div class="detail-section">
    <h2>Claim</h2>
    {% for label, content in claim.sections.items() %}
    <div class="section-block">
      <div class="section-label">{{ label }}</div>
      <div class="section-text">{{ content }}</div>
    </div>
    {% endfor %}
  </div>
  {% else %}
  <div class="detail-section">
    <h2>Claim</h2>
    <p class="section-text">{{ claim.text }}</p>
  </div>
  {% endif %}

  <div class="detail-section">
    <h2>Metadata</h2>
    <p class="cid">{{ claim.cid }}</p>
    <p class="meta">{{ claim.author }} &middot; {{ claim.timestamp }}</p>
    {% for d in claim.domains %}<span class="domain-tag">{{ d }}</span> {% endfor %}
  </div>

  {% if claim.parents %}
  <div class="detail-section">
    <h2>Parents</h2>
    {% for p in claim.parents %}
    <div class="lineage-item">
      <span class="badge badge-{{ p.type }}">{{ p.type }}</span>
      <a href="{{ p.cid }}.html">{{ p.text }}</a>
      <span class="cid">{{ p.short_cid }}</span>
    </div>
    {% endfor %}
  </div>
  {% endif %}

  {% if claim.children %}
  <div class="detail-section">
    <h2>Children</h2>
    {% for ch in claim.children %}
    <div class="lineage-item">
      <span class="badge badge-{{ ch.type }}">{{ ch.type }}</span>
      <a href="{{ ch.cid }}.html">{{ ch.text }}</a>
      <span class="cid">{{ ch.short_cid }}</span>
    </div>
    {% endfor %}
  </div>
  {% endif %}

  {% if claim.evidence %}
  <div class="detail-section">
    <h2>Evidence</h2>
    {% for ev in claim.evidence %}
    <div class="lineage-item">
      <span class="cid">{{ ev.short_cid }}</span>
      {{ ev.filename }} &middot; {{ ev.media_type }} &middot; {{ ev.size }} bytes
    </div>
    {% endfor %}
  </div>
  {% endif %}
</div>
</body>
</html>
"""

_THREAD_CSS = """\
.thread-card { background: var(--card); border: 1px solid var(--border); border-radius: 0.5rem;
  padding: 1rem; margin-bottom: 0.75rem; border-left: 3px solid var(--border); }
.thread-card[data-status="open"] { border-left-color: var(--hypothesis); }
.thread-card[data-status="confirmed"] { border-left-color: var(--result); }
.thread-card[data-status="refuted"] { border-left-color: var(--refutation); }
.thread-card[data-status="mixed"] { border-left-color: var(--equivalence); }
.status-badge { display: inline-block; padding: 0.1rem 0.5rem; border-radius: 0.75rem;
  font-size: 0.7rem; font-weight: 600; text-transform: uppercase; }
.status-open { background: var(--hypothesis); color: #000; }
.status-confirmed { background: var(--result); color: #fff; }
.status-refuted { background: var(--refutation); color: #fff; }
.status-mixed { background: var(--equivalence); color: #fff; }
.thread-meta { display: flex; gap: 1rem; color: var(--muted); font-size: 0.8rem; margin-top: 0.25rem; }
"""

_THREAD_INDEX_TEMPLATE = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Research Threads</title>
<style>""" + _CSS + _THREAD_CSS + """</style>
</head>
<body>
<div class="container">
  <p><a href="../index.html">&larr; Back to DAG</a></p>
  <header>
    <h1>Research Threads</h1>
    <span class="meta">{{ count }} threads</span>
  </header>

  {% for t in threads %}
  <div class="thread-card" data-status="{{ t.status }}">
    <span class="status-badge status-{{ t.status }}">{{ t.status_icon }} {{ t.status }}</span>
    <div class="claim-text"><a href="{{ t.hypothesis_cid }}.html">{{ t.hypothesis_text }}</a></div>
    <div class="thread-meta">
      <span class="cid">{{ t.hypothesis_short_cid }}</span>
      <span>{{ t.claim_count }} claims</span>
      <span>{{ t.first_date }}–{{ t.last_date }}</span>
      {% for d in t.domains %}<span class="domain-tag">{{ d }}</span>{% endfor %}
    </div>
  </div>
  {% endfor %}
</div>
</body>
</html>
"""

_THREAD_DETAIL_TEMPLATE = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Thread: {{ thread.hypothesis_text[:60] }}</title>
<style>""" + _CSS + _THREAD_CSS + """</style>
</head>
<body>
<div class="container">
  <p><a href="index.html">&larr; All Threads</a></p>

  <header>
    <h1>{{ thread.hypothesis_text }}</h1>
    <span class="status-badge status-{{ thread.status }}">{{ thread.status_icon }} {{ thread.status }}</span>
  </header>

  <div class="thread-meta" style="margin-bottom:1.5rem">
    <span class="cid">{{ thread.hypothesis_short_cid }}</span>
    <span>{{ thread.claim_count }} claims</span>
    <span>{{ thread.first_date }}–{{ thread.last_date }}</span>
    {% for d in thread.domains %}<span class="domain-tag">{{ d }}</span>{% endfor %}
  </div>

  <div class="detail-section">
    <h2>Claims</h2>
    {% for c in thread.claims %}
    <div class="claim-card" data-type="{{ c.type }}">
      <span class="badge badge-{{ c.type }}">{{ c.type }}</span>
      <div class="claim-text"><a href="../claims/{{ c.cid }}.html">{{ c.text }}</a></div>
      <div class="claim-meta">
        <span class="cid">{{ c.short_cid }}</span>
        <span>{{ c.date }}</span>
        {% for d in c.domains %}<span class="domain-tag">{{ d }}</span>{% endfor %}
      </div>
    </div>
    {% endfor %}
  </div>
</div>
</body>
</html>
"""

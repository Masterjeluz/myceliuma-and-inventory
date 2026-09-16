"""Living Workshop visual system (BIG #19).

One design language for every coordinator page: dark-earth
SolarPunk tokens, a three-column workshop shell (world nav
/ workspace / context), organic status language, and
shared components. Pages supply content; this module owns
all presentation. Backend calls stay where they were —
this layer never fetches data itself (callers pass rows).

Accessibility: semantic landmarks, visible focus,
prefers-reduced-motion kills animation, contrast-checked
palette (warm off-white on near-black soil).
"""

from html import escape as _escape


def esc(value) -> str:
    return _escape(str(value or ""), quote=True)


TOKENS = """
:root{
--soil:#101410; --soil-2:#161c16; --surface:#1b221b; --surface-2:#222b22;
--line:#2e3a2c; --line-soft:#263026;
--ink:#ece7d8; --ink-dim:#b9bfae; --ink-faint:#8a9184;
--moss:#7d9b6a; --moss-bright:#a5c48a; --fern:#4c6b4f;
--amber:#d9a441; --amber-dim:#8a6a2c;
--spore:#c9d66b; --root:#6b5844;
--danger:#c96a5a; --ok:#8fb573;
--font: "Segoe UI", system-ui, -apple-system, sans-serif;
--mono: "Cascadia Code", Consolas, monospace;
--r:10px; --r-sm:6px;
--space-1:.4rem; --space-2:.8rem; --space-3:1.2rem; --space-4:2rem;
--ease:cubic-bezier(.22,.9,.28,1);
}
"""

BASE_CSS = TOKENS + """
*{box-sizing:border-box}
html{-webkit-text-size-adjust:100%}
body{margin:0;background:var(--soil);color:var(--ink);font-family:var(--font);font-size:15px;line-height:1.55}
a{color:var(--moss-bright)}
a:focus-visible,button:focus-visible,input:focus-visible,select:focus-visible,textarea:focus-visible,[tabindex]:focus-visible{outline:2px solid var(--amber);outline-offset:2px;border-radius:4px}
.shell{min-height:100vh;display:grid;grid-template-columns:230px minmax(0,1fr) 300px;grid-template-rows:auto minmax(0,1fr) auto;grid-template-areas:"top top top" "nav main aside" "cmd cmd cmd"}
.topbar{grid-area:top;display:flex;align-items:center;gap:var(--space-2);padding:.55rem var(--space-3);background:var(--soil-2);border-bottom:1px solid var(--line)}
.topbar .spacer{flex:1}
.topbar .ext{font-size:.8rem;color:var(--ink-dim)}
.brand{font-weight:700;letter-spacing:.14em;font-size:.85rem;color:var(--spore)}
.brand small{color:var(--ink-faint);letter-spacing:.04em;font-weight:400}
.sidenav{grid-area:nav;border-right:1px solid var(--line);padding:var(--space-2);background:var(--soil-2)}
.sidenav h4{margin:var(--space-2) 0 .3rem;font-size:.68rem;letter-spacing:.16em;text-transform:uppercase;color:var(--ink-faint)}
.sidenav a{display:block;padding:.42rem .6rem;border-radius:var(--r-sm);color:var(--ink-dim);text-decoration:none;border:1px solid transparent}
.sidenav a:hover{background:var(--surface);color:var(--ink)}
.sidenav a[aria-current="page"]{background:var(--surface-2);border-color:var(--line);color:var(--spore)}
.workspace{grid-area:main;padding:var(--space-3);min-width:0;max-width:1100px}
.context{grid-area:aside;border-left:1px solid var(--line);padding:var(--space-2);background:var(--soil-2);font-size:.88rem}
.cmdbar{grid-area:cmd;border-top:1px solid var(--line);background:var(--soil-2);padding:.6rem var(--space-3)}
.cmdbar form{display:flex;gap:.5rem;max-width:1100px}
.cmdbar input[type=text]{flex:1;background:var(--surface);border:1px solid var(--line);color:var(--ink);border-radius:var(--r-sm);padding:.55rem .7rem}
h1{font-size:1.35rem;margin:.2rem 0 var(--space-2);letter-spacing:.01em}
h2{font-size:1.02rem;margin:var(--space-3) 0 var(--space-1);color:var(--moss-bright)}
h3{font-size:.92rem;margin:var(--space-2) 0 .4rem}
.panel{background:var(--surface);border:1px solid var(--line);border-radius:var(--r);padding:var(--space-2) var(--space-3);margin-bottom:var(--space-2)}
.grove{display:grid;grid-template-columns:repeat(auto-fill,minmax(240px,1fr));gap:var(--space-2)}
.sprout{background:var(--surface);border:1px solid var(--line);border-radius:var(--r);padding:var(--space-2);transition:border-color .25s var(--ease),transform .25s var(--ease)}
.sprout:hover{border-color:var(--fern)}
table{width:100%;border-collapse:collapse;background:var(--surface);border:1px solid var(--line);border-radius:var(--r);overflow:hidden;margin-bottom:var(--space-2)}
td,th{padding:.55rem .7rem;text-align:left;border-bottom:1px solid var(--line-soft);font-size:.9rem}
th{color:var(--ink-faint);font-weight:600;font-size:.75rem;letter-spacing:.08em;text-transform:uppercase}
tr:last-child td{border-bottom:none}
code{font-family:var(--mono);background:var(--soil-2);padding:.1rem .35rem;border-radius:4px;font-size:.85em;color:var(--spore)}
button,.btn{background:var(--fern);color:var(--ink);border:1px solid var(--line);border-radius:var(--r-sm);padding:.5rem .9rem;cursor:pointer;font-size:.9rem}
button:hover,.btn:hover{background:#5a7d5c}
input[type=text],select,textarea{background:var(--surface);border:1px solid var(--line);color:var(--ink);border-radius:var(--r-sm);padding:.5rem .6rem;font-size:.9rem;max-width:100%}
.dot{display:inline-block;width:.6em;height:.6em;border-radius:50%;margin-right:.45em;vertical-align:baseline}
.dot.online,.dot.ok,.dot.completed,.dot.verified{background:var(--ok);box-shadow:0 0 6px var(--ok)}
.dot.busy,.dot.running,.dot.assigned,.dot.pending,.dot.proposed{background:var(--amber);box-shadow:0 0 6px var(--amber)}
.dot.stale,.dot.paused,.dot.degraded{background:var(--amber-dim)}
.dot.offline,.dot.failed,.dot.blocked,.dot.disabled{background:var(--danger)}
.dot.unknown,.dot.draft,.dot.cancelled{background:var(--ink-faint)}
.sr{position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0 0 0 0);white-space:nowrap}
.chip{display:inline-block;font-size:.72rem;letter-spacing:.06em;text-transform:uppercase;border:1px solid var(--line);border-radius:99px;padding:.12rem .55rem;color:var(--ink-dim);margin:.1rem .15rem .1rem 0}
.chip.truth-verified,.chip.truth-user_fact{border-color:var(--moss);color:var(--moss-bright)}
.chip.truth-ai_inference,.chip.truth-ai_suggestion{border-color:var(--amber-dim);color:var(--amber)}
.chip.state-LIVE,.chip.state-AVAILABLE{border-color:var(--moss);color:var(--moss-bright)}
.chip.state-MOCK,.chip.state-SIMULATED,.chip.state-TEST{border-color:var(--amber);color:var(--amber)}
.chip.state-UNAVAILABLE{border-color:var(--danger);color:var(--danger)}
.path{display:flex;flex-wrap:wrap;gap:.3rem;align-items:center;margin:.6rem 0}
.path .step{background:var(--surface-2);border:1px solid var(--line);border-radius:var(--r-sm);padding:.3rem .6rem;font-size:.82rem}
.path .step.done{border-color:var(--fern);color:var(--moss-bright)}
.path .step.now{border-color:var(--amber);color:var(--amber)}
.path .step.blocked{border-color:var(--danger);color:var(--danger)}
.path .arrow{color:var(--ink-faint)}
.empty{color:var(--ink-faint);font-style:italic;padding:var(--space-2)}
.muted{color:var(--ink-faint);font-size:.85rem}
.flowline{display:flex;gap:.4rem;align-items:center;flex-wrap:wrap}
svg.world{width:100%;height:auto;background:var(--soil-2);border:1px solid var(--line);border-radius:var(--r)}
svg.world .w-node{cursor:pointer}
svg.world .w-node:focus{outline:2px solid var(--amber);outline-offset:2px}
svg.world text{fill:var(--ink-dim);font-size:11px;font-family:var(--font)}
@media (prefers-reduced-motion:reduce){*{animation:none!important;transition:none!important}}
.breathe{animation:breathe 5s ease-in-out infinite}
@keyframes breathe{0%,100%{opacity:.75}50%{opacity:1}}
.pulse{animation:pulse 2.2s ease-out infinite}
@keyframes pulse{0%{opacity:.9}70%{opacity:.35}100%{opacity:.9}}
@media (max-width:1080px){.shell{grid-template-columns:200px minmax(0,1fr);grid-template-areas:"top top" "nav main" "cmd cmd"}.context{display:none}}
@media (max-width:720px){.shell{grid-template-columns:minmax(0,1fr);grid-template-areas:"top" "main" "cmd"}.sidenav{display:flex;overflow-x:auto;gap:.2rem;border-right:none;border-bottom:1px solid var(--line)}.sidenav h4{display:none}.sidenav a{white-space:nowrap}.workspace{padding:var(--space-2)}}
"""

NAV = [
    ("WORLD", [("/", "Living World"), ("/world", "World Graph"),
               ("/projects", "Projects"), ("/memory", "Memory")]),
    ("MIND", [("/missions", "Missions"), ("/chat", "Chat"),
              ("/research", "Research"), ("/morning", "Morning")]),
    ("ACTIVITY", [("/activity", "Activity"), ("/watcher", "Watcher"),
                  ("/agents", "Agents")]),
    ("PHYSICAL", [("/workshop", "Workshop"),
                  ("/fabrication", "Fabrication"),
                  ("/devices", "Devices"),
                  ("/cameras", "Cameras")]),
    ("SYSTEM", [("/skills", "Skills"), ("/health", "Health"),
                ("/mobile", "Mobile")]),
]


def nav_html(active: str) -> str:
    parts = []
    for group, links in NAV:
        parts.append(f"<h4>{esc(group)}</h4>")
        for href, label in links:
            current = ' aria-current="page"' if href == active \
                else ""
            parts.append(
                f'<a href="{esc(href)}"{current}>{esc(label)}</a>')
    return "<nav class=\"sidenav\" aria-label=\"Workshop areas\">" + \
        "".join(parts) + "</nav>"


def status_dot(status: str) -> str:
    key = str(status or "unknown").strip().lower()
    return f"<span class=\"dot {esc(key)}\" aria-hidden=\"true\"" \
        f"></span><span class=\"sr\">{esc(status)}</span>"


def chip(text: str, kind: str = "") -> str:
    return f"<span class=\"chip {esc(kind)}\">{esc(text)}</span>"


def truth_chip(truth: str) -> str:
    return chip(str(truth).replace("_", " "),
                f"truth-{truth}")


def state_chip(state: str) -> str:
    return chip(state, f"state-{state}")


def empty(text: str = "Nothing here yet.") -> str:
    return f"<p class=\"empty\">{esc(text)}</p>"


def shell(title: str, active: str, main: str, context: str = "",
          command: str = "") -> str:
    """Full workshop shell. `main` is the workspace column,
    `context` the right rail, `command` the bottom bar."""
    context_html = f"<aside class=\"context\" " \
        f"aria-label=\"Context\">{context}</aside>" if context \
        else ""
    cmd_html = f"<div class=\"cmdbar\">{command}</div>" \
        if command else ""
    return f"""<!doctype html><html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(title)} — Mycelium Living Workshop</title>
<style>{BASE_CSS}</style></head>
<body><div class="shell">
<header class="topbar"><span class="brand">MYCELIUM <small>living workshop · local-first</small></span><span class="spacer"></span><a class="ext" href="http://127.0.0.1:8080" target="_blank" rel="noopener">INVENTory :8080</a> <a class="ext" href="/api/v1/agent/status">agent JSON</a></header>
{nav_html(active)}
<main class="workspace" id="main">{main}</main>
{context_html}
{cmd_html}
</div></body></html>"""


def command_bar(action: str = "/web/chat",
                placeholder: str = "Ask Mycelium…") -> str:
    return f"""<form method="post" action="{esc(action)}" role="search" aria-label="Ask Mycelium">
<input type="text" name="message" placeholder="{esc(placeholder)}" aria-label="Message" autocomplete="off">
<button type="submit">Send</button></form>"""


def context_block(title: str, body: str) -> str:
    return f"<section class=\"panel\"><h3>{esc(title)}</h3>{body}</section>"


def kv_list(rows) -> str:
    items = "".join(
        f"<tr><th scope=\"row\">{esc(key)}</th><td>{value}</td></tr>"
        for key, value in rows)
    return f"<table><tbody>{items}</tbody></table>"


def link_entities(text: str) -> str:
    """Linkify world/memory/mission ids in prose. Entity ids
    focus the world graph; memories open the memory page."""
    import re
    safe = esc(text)
    def world_link(match):
        ident = match.group(0)
        return f"<a href=\"/world?entity_id={ident}\"><code>{ident}</code></a>"
    safe = re.sub(r"\b(obj|proj|idea|loc|hw|file)_[A-Za-z0-9._-]+\b",
                  world_link, safe)
    def mem_link(match):
        ident = match.group(0)
        return f"<a href=\"/memory\"><code>{ident}</code></a>"
    safe = re.sub(r"\bmem_[A-Za-z0-9]+\b", mem_link, safe)
    def mission_link(match):
        ident = match.group(0)
        return f"<a href=\"/missions/{ident}\"><code>{ident}</code></a>"
    safe = re.sub(r"\bmission_[A-Za-z0-9]+\b", mission_link, safe)
    return safe


# -- world graph -----------------------------------------------------------
# Organic visual grammar (SVG, no framework):
# object: moss circle · project: double ring cluster ·
# idea: seed diamond · memory/mission: luminous halo ·
# node: technical square · observation: small pulse ·
# event: short-lived particle · task: amber circle ·
# source ring: world solid, mycelium dashed, conflict red.
# Bounded server data in, pan/zoom/select/focus/expand out.

GRAPH_JS = """
constWGDATA;
let scale = 1, tx = 0, ty = 0, selected = null;
const svg = document.getElementById('wstage');
const NS = 'http://www.w3.org/2000/svg';
function wcolor(n){
  if ((n.metadata && n.metadata.status === 'conflict') || n.type === 'conflict') return 'var(--danger)';
  if (n.source === 'inventory') return 'var(--moss)';
  if (n.kind === 'memory' || n.type === 'memory') return 'var(--spore)';
  if (n.kind === 'mission' || n.type === 'mission') return 'var(--amber)';
  return 'var(--ink-dim)';
}
function wkind(n){ return (n.kind || n.type || 'entity').toLowerCase(); }
function wvisible(n){
  const f = id => document.getElementById(id).checked;
  if (wcolor(n) === 'var(--danger)') return f('f-conflict');
  const t = document.getElementById('f-type').value;
  if (t !== 'all' && wkind(n) !== t) return false;
  return n.source === 'inventory' ? f('f-world') : f('f-mycelium');
}
function wlayout(){
  const nodes = WGDATA.nodes.filter(wvisible);
  const byId = {};
  nodes.forEach((n, i) => {
    const a = 2 * Math.PI * i / Math.max(1, nodes.length);
    const r = n.source === 'inventory' ? 150 : 210;
    byId[n.id] = {x: 500 + r * Math.cos(a), y: 240 + r * Math.sin(a), n};
  });
  return byId;
}
function wshape(g, p){
  const k = wkind(p.n), c = wcolor(p.n), id = p.n.id;
  const grp = document.createElementNS(NS, 'g');
  grp.setAttribute('class', 'w-node');
  grp.setAttribute('tabindex', '0');
  grp.setAttribute('role', 'button');
  grp.setAttribute('aria-label', (p.n.label || id) + ' (' + k + ')');
  const halo = (k === 'memory' || k === 'mission');
  if (halo) {
    const h = document.createElementNS(NS, 'circle');
    h.setAttribute('cx', p.x); h.setAttribute('cy', p.y); h.setAttribute('r', 16);
    h.setAttribute('fill', 'none'); h.setAttribute('stroke', c);
    h.setAttribute('stroke-opacity', '.35'); h.setAttribute('stroke-width', '5');
    h.setAttribute('class', 'breathe'); grp.appendChild(h);
  }
  let el;
  if (k === 'idea') {
    el = document.createElementNS(NS, 'rect');
    el.setAttribute('x', p.x - 7); el.setAttribute('y', p.y - 7);
    el.setAttribute('width', 14); el.setAttribute('height', 14);
    el.setAttribute('transform', `rotate(45 ${p.x} ${p.y})`);
  } else if (k === 'node' || k === 'device' || k === 'printer') {
    el = document.createElementNS(NS, 'rect');
    el.setAttribute('x', p.x - 7); el.setAttribute('y', p.y - 7);
    el.setAttribute('width', 14); el.setAttribute('height', 14);
    el.setAttribute('rx', 2);
  } else {
    el = document.createElementNS(NS, 'circle');
    el.setAttribute('cx', p.x); el.setAttribute('cy', p.y);
    const r = k === 'project' ? 12 : k === 'observation' || k === 'event' ? 5 : 8;
    el.setAttribute('r', id === selected ? r + 4 : r);
  }
  el.setAttribute('fill', k === 'project' ? 'none' : c);
  el.setAttribute('stroke', c);
  el.setAttribute('stroke-width', k === 'project' ? 3 : 1.5);
  if (p.n.source !== 'inventory') el.setAttribute('stroke-dasharray', '4 2');
  if (k === 'observation') el.setAttribute('class', 'pulse');
  grp.appendChild(el);
  const t = document.createElementNS(NS, 'text');
  t.setAttribute('x', p.x + 13); t.setAttribute('y', p.y + 4);
  t.textContent = (p.n.label || id).slice(0, 26);
  grp.appendChild(t);
  const pick = () => wselect(p.n);
  grp.addEventListener('click', pick);
  grp.addEventListener('keydown', e => {
    if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); pick(); }
  });
  g.appendChild(grp);
}
function wrender(){
  while (svg.firstChild) svg.removeChild(svg.firstChild);
  const g = document.createElementNS(NS, 'g');
  g.setAttribute('transform', `translate(${tx},${ty}) scale(${scale})`);
  svg.appendChild(g);
  const byId = wlayout();
  (WGDATA.edges || []).forEach(e => {
    if (!byId[e.from] || !byId[e.to]) return;
    const l = document.createElementNS(NS, 'line');
    l.setAttribute('x1', byId[e.from].x); l.setAttribute('y1', byId[e.from].y);
    l.setAttribute('x2', byId[e.to].x); l.setAttribute('y2', byId[e.to].y);
    l.setAttribute('stroke', 'var(--line)'); l.setAttribute('stroke-width', '1.5');
    l.style.cursor = 'pointer';
    l.addEventListener('click', () => wselectEdge(e));
    g.appendChild(l);
    const t = document.createElementNS(NS, 'text');
    t.setAttribute('x', (byId[e.from].x + byId[e.to].x) / 2);
    t.setAttribute('y', (byId[e.from].y + byId[e.to].y) / 2 - 3);
    t.setAttribute('font-size', '9'); t.setAttribute('fill', 'var(--ink-faint)');
    t.textContent = e.predicate || '';
    g.appendChild(t);
  });
  Object.values(byId).forEach(p => wshape(g, p));
  const n = WGDATA.nodes.filter(wvisible).length;
  document.getElementById('wcount').textContent = n + ' shown / ' + WGDATA.nodes.length + ' loaded';
}
function wdetails(html){ document.getElementById('wdetails').innerHTML = html; }
function wselect(n){
  selected = n.id;
  const meta = n.metadata || {};
  const rows = [['id', n.id], ['kind', wkind(n)], ['source', n.source || '?']]
    .map(([k, v]) => `<tr><th scope="row">${k}</th><td>${String(v).replace(/</g, '&lt;')}</td></tr>`).join('');
  let links = '';
  if (String(n.id).match(/^(obj_|proj_|idea_|loc_|hw_|file_)/))
    links += `<p><a href="/world?entity_id=${encodeURIComponent(n.id)}">Open neighborhood</a></p>`;
  if (String(n.id).startsWith('mem_'))
    links += `<p><a href="/memory">Open in memory</a></p>`;
  if (String(n.id).startsWith('prt-'))
    links += `<p><a href="/devices">Open in devices</a></p>`;
  wdetails(`<table><tbody>${rows}</tbody></table>`
    + `<details><summary>metadata</summary><code>${JSON.stringify(meta).replace(/</g, '&lt;')}</code></details>` + links);
  wrender();
}
function wselectEdge(e){
  wdetails(`<table><tbody><tr><th scope="row">relation</th><td>${String(e.predicate || '').replace(/</g, '&lt;')}</td></tr>`
    + `<tr><th scope="row">from</th><td>${String(e.from).replace(/</g, '&lt;')}</td></tr>`
    + `<tr><th scope="row">to</th><td>${String(e.to).replace(/</g, '&lt;')}</td></tr></tbody></table>`);
}
document.getElementById('wzin').addEventListener('click', () => { scale *= 1.2; wrender(); });
document.getElementById('wzout').addEventListener('click', () => { scale /= 1.2; wrender(); });
document.getElementById('wfocus').addEventListener('click', () => { tx = 0; ty = 0; scale = 1; wrender(); });
['f-world', 'f-mycelium', 'f-conflict'].forEach(id =>
  document.getElementById(id).addEventListener('change', wrender));
document.getElementById('f-type').addEventListener('change', wrender);
let wdrag = null;
svg.addEventListener('pointerdown', e => { wdrag = [e.clientX, e.clientY]; svg.setPointerCapture(e.pointerId); });
svg.addEventListener('pointerup', () => wdrag = null);
svg.addEventListener('pointermove', e => {
  if (!wdrag) return;
  tx += e.clientX - wdrag[0]; ty += e.clientY - wdrag[1];
  wdrag = [e.clientX, e.clientY]; wrender();
});
svg.addEventListener('wheel', e => {
  e.preventDefault();
  scale *= e.deltaY < 0 ? 1.1 : 0.9; wrender();
}, {passive: false});
wrender();
"""


def graph_panel(data_json: str, form_action: str, entity_id: str = "",
                depth: int = 1, show: str = "missions,nodes",
                error: str = "") -> str:
    """Interactive world graph: form + SVG stage + details.
    `data_json` is the already-serialized graph dict."""
    safe_data = data_json.replace("</", "<\\/")
    return f"""<div class="panel"><form method="get" action="{esc(form_action)}" role="search" aria-label="Graph focus">
<label>Entity <input type="text" name="entity_id" placeholder="obj_… / proj_… / mem_…" value="{esc(entity_id)}" style="width:16rem"></label>
<label>Depth <input type="number" name="depth" value="{esc(depth)}" min="1" max="2" style="width:3.5rem"></label>
<label>Overlays <input type="text" name="show" value="{esc(show)}" style="width:12rem"></label>
<button type="submit">Grow</button></form>
<p class="muted">world <span class="dot online"></span> · mycelium overlay (dashed) · memory <span class="dot" style="background:var(--spore)"></span> · mission <span class="dot" style="background:var(--amber)"></span> · conflict <span class="dot" style="background:var(--danger)"></span></p>
<p><small>Show:</small>
<label><input type="checkbox" id="f-world" checked> world</label>
<label><input type="checkbox" id="f-mycelium" checked> mycelium</label>
<label><input type="checkbox" id="f-conflict" checked> conflict</label>
<label>Type <select id="f-type"><option value="all">all</option><option value="object">objects</option><option value="project">projects</option><option value="idea">ideas</option><option value="memory">memories</option><option value="mission">missions</option><option value="task">tasks</option><option value="node">nodes</option><option value="observation">observations</option><option value="event">events</option></select></label>
<button id="wzin" aria-label="Zoom in">+</button><button id="wzout" aria-label="Zoom out">−</button>
<button id="wfocus">Reset view</button>
<span id="wcount" class="muted" role="status"></span></p>
<p style="color:var(--danger)">{esc(error)}</p></div>
<svg id="wstage" class="world" viewBox="0 0 1000 480" role="application" aria-label="World graph. Tab to move between nodes, Enter to select."></svg>
<div class="panel"><h2>Details</h2><div id="wdetails">Select a node or relation. Keyboard: Tab to a node, Enter to open.</div></div>
<script>const WGDATA = {safe_data};
{GRAPH_JS.replace("constWGDATA;", "")}</script>"""

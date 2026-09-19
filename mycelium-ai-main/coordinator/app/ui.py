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
body{margin:0;background:var(--soil);background-image:radial-gradient(1100px 420px at 50% -120px, #1b231b 0%, var(--soil) 70%);color:var(--ink);font-family:var(--font);font-size:15px;line-height:1.55}
a{color:var(--moss-bright)}
a:focus-visible,button:focus-visible,input:focus-visible,select:focus-visible,textarea:focus-visible,[tabindex]:focus-visible{outline:2px solid var(--amber);outline-offset:2px;border-radius:4px}
.shell{min-height:100vh;display:grid;grid-template-columns:230px minmax(0,1fr) 300px;grid-template-rows:auto minmax(0,1fr) auto;grid-template-areas:"top top top" "nav main aside" "cmd cmd cmd"}
.topbar{grid-area:top;display:flex;align-items:center;gap:var(--space-2);padding:.55rem var(--space-3);background:var(--soil-2);border-bottom:1px solid var(--line)}
.topbar .spacer{flex:1}
.topbar .ext{font-size:.8rem;color:var(--ink-dim);white-space:nowrap}
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
.sprout{background:var(--surface);border:1px solid var(--line);border-top:2px solid var(--fern);border-radius:var(--r);padding:var(--space-2);transition:border-color .25s var(--ease),transform .25s var(--ease)}
.sprout:hover{border-color:var(--moss);border-top-color:var(--moss);transform:translateY(-2px)}
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
.filament{height:14px;background-repeat:repeat-x;background-position:center;opacity:.5;
background-image:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='72' height='14'%3E%3Cpath d='M0 10 C 18 4, 30 12, 44 7 S 64 4, 72 8' fill='none' stroke='%234c6b4f' stroke-width='1.4'/%3E%3Ccircle cx='22' cy='8' r='1.8' fill='%237d9b6a'/%3E%3Ccircle cx='52' cy='6' r='1.5' fill='%23c9d66b'/%3E%3C/svg%3E")}
.sun{background:linear-gradient(180deg, rgba(217,164,65,.10), rgba(217,164,65,0) 70%)}
.grain{position:relative}
.grain::after{content:"";position:absolute;inset:0;pointer-events:none;opacity:.05;border-radius:inherit;
background-image:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='90' height='90'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='.9' numOctaves='2'/%3E%3C/filter%3E%3Crect width='90' height='90' filter='url(%23n)' opacity='.6'/%3E%3C/svg%3E")}
.growth-seed{border-top:2px dotted var(--ink-faint)}
.growth-sprout{border-top:2px solid var(--fern)}
.growth-grown{border-top:2px solid var(--moss-bright)}
.growth-bloom{border-top:2px solid var(--amber)}
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
@media (max-width:720px){.shell{grid-template-columns:minmax(0,1fr);grid-template-areas:"top" "nav" "main" "cmd"}.sidenav{grid-area:nav;display:flex;overflow-x:auto;gap:.2rem;border-right:none;border-bottom:1px solid var(--line);align-items:center}.sidenav h4{display:none}.sidenav a{white-space:nowrap;border:none}.brand{font-size:.75rem}.brand small{display:none}.workspace{padding:var(--space-2)}}
/* BIG #33 living world: pixel-organic accents, state language, quest/craft/guide */
button,.btn{box-shadow:inset 0 -3px 0 rgba(0,0,0,.28),inset 0 2px 0 rgba(255,255,255,.08);image-rendering:pixelated}
.panel{position:relative}
.panel.living{border-top:2px solid var(--moss);overflow:hidden}
.living-bg{position:fixed;inset:0;z-index:-1;pointer-events:none;opacity:.5;
background-image:radial-gradient(900px 380px at 20% -80px, rgba(125,155,106,.10), transparent 70%),
radial-gradient(700px 320px at 85% 10%, rgba(217,164,65,.07), transparent 70%),
radial-gradient(500px 500px at 50% 110%, rgba(76,107,79,.12), transparent 70%)}
.living-canvas{position:fixed;inset:0;z-index:-1;pointer-events:none;opacity:.55}
.state-real{border-color:var(--moss);color:var(--moss-bright)}
.state-test{border-color:var(--amber);color:var(--amber);border-style:dashed}
.state-simulated{border-color:var(--amber-dim);color:var(--ink-dim);border-style:dashed}
.state-unavailable{border-color:var(--ink-faint);color:var(--ink-faint)}
.state-waiting{border-color:var(--amber);color:var(--amber)}
.state-active{border-color:var(--moss-bright);color:var(--moss-bright)}
.state-blocked{border-color:var(--danger);color:var(--danger)}
.state-verified{border-color:var(--moss);color:var(--moss-bright);box-shadow:0 0 8px rgba(125,155,106,.35)}
.state-candidate{border-color:var(--fern);color:var(--spore)}
.state-observation{border-color:var(--line);color:var(--ink-dim)}
.sym-PROPOSED{border-color:var(--amber-dim);color:var(--amber)}
.sym-SUPPORTED{border-color:var(--moss);color:var(--moss-bright)}
.sym-VERIFIED{border-color:var(--moss-bright);color:var(--moss-bright);box-shadow:0 0 8px rgba(165,196,138,.4)}
.quest{list-style:none;margin:.4rem 0;padding:0}
.quest li{display:flex;gap:.5rem;align-items:baseline;padding:.25rem 0}
.quest .q-done{color:var(--moss-bright)}
.quest .q-now{color:var(--amber)}
.quest .q-todo{color:var(--ink-faint)}
.growthbar{display:flex;align-items:center;gap:.3rem;margin:.5rem 0}
.growthbar .g{height:8px;flex:1;border-radius:99px;background:var(--soil-2);border:1px solid var(--line)}
.growthbar .g.on{background:linear-gradient(90deg,var(--fern),var(--moss-bright));border-color:var(--moss)}
.craft{display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:var(--space-2)}
.craft-stage{background:var(--surface);border:1px solid var(--line);border-radius:var(--r);padding:var(--space-2)}
.craft-stage.full{border-top:2px solid var(--moss-bright)}
.craft-stage.empty{border-top:2px dotted var(--ink-faint);opacity:.85}
.guide-card{border-left:3px solid var(--moss)}
.guide-card.kind-approval{border-left-color:var(--amber)}
.guide-card.kind-node{border-left-color:var(--amber-dim)}
.empty-hero{text-align:center;padding:var(--space-3)}
.empty-hero .sprout-char{font-size:2rem}
.timeline{list-style:none;margin:0;padding:0}
.timeline li{position:relative;padding:.35rem 0 .35rem 1.2rem;border-left:2px solid var(--line);margin-left:.4rem}
.timeline li::before{content:"";position:absolute;left:-5px;top:.8em;width:8px;height:8px;border-radius:50%;background:var(--moss)}
.timeline li.wait::before{background:var(--amber);box-shadow:0 0 6px var(--amber)}
/* BIG #38 living automation: subtle motion on real state only.
   Global reduced-motion rule above kills all of this on request. */
.sym-PROPOSED{animation:breathe 6s ease-in-out infinite}
.auto-wait{border-left:3px solid var(--amber)}
.auto-wait .q-now{animation:pulse 2.2s ease-out infinite}
.craft-stage.gap{border-top:2px dashed var(--amber-dim)}
.discovery{border-left:3px solid var(--spore)}
.discovery .burst{color:var(--spore)}
/* BIG #40 presence ecosystem: the world reacts to attention.
   Subtle motion on real state only; the global reduced-motion
   rule above kills all of this on request. */
.dot.online{animation:breathe 5s ease-in-out infinite}
.dim-offline{opacity:.55}
.band-needs{border-left:3px solid var(--danger)}
.band-waiting{border-left:3px solid var(--amber)}
.band-available{border-left:3px solid var(--moss)}
.band-discovered{border-left:3px solid var(--spore)}
.band-offline{border-left:3px solid var(--ink-faint);opacity:.85}
.quest-marker{border-left:3px solid var(--amber)}
.growth-event{border-left:3px solid var(--moss-bright)}
.presence-chip{font-size:.8rem;color:var(--ink-dim)}
.presence-chip a{color:var(--ink-dim)}
.quickgrid{display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:.5rem;margin:.6rem 0}
.quickgrid a{display:block;text-align:center;background:var(--surface-2);border:1px solid var(--line);border-radius:var(--r-sm);padding:.7rem .4rem;text-decoration:none;font-size:1.4rem}
.quickgrid a small{display:block;font-size:.72rem;color:var(--ink-dim);margin-top:.2rem}
@media (prefers-reduced-motion:reduce){.living-canvas{display:none}}
"""

NAV = [
    ("WORLD", [("/", "Living World"), ("/world", "World Graph"),
               ("/craft", "Craft Tree"), ("/guide", "Guide"),
               ("/symbiosis", "Symbiosis"),
               ("/search", "Search"), ("/projects", "Projects"),
               ("/memory", "Memory"), ("/knowledge", "Knowledge"),
               ("/conversations", "Conversations")]),
    ("MIND", [("/missions", "Missions"), ("/chat", "Chat"),
              ("/research", "Research"), ("/morning", "Morning"),
              ("/agenda", "Agenda")]),
    ("ACTIVITY", [("/activity", "Activity"), ("/watcher", "Watcher"),
                  ("/agents", "Agents")]),
    ("PHYSICAL", [("/workshop", "Workshop"), ("/workshop/3d", "3D"),
                  ("/fabrication", "Fabrication"),
                  ("/devices", "Devices"), ("/nodes", "Nodes"),
                  ("/cameras", "Cameras")]),
    ("SYSTEM", [("/skills", "Skills"), ("/health", "Health"),
                ("/writes", "Writes"), ("/mobile", "Mobile")]),
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


MISSION_GLYPHS = {
    "running": "🟢",
    "approved": "🟢",
    "pending_approval": "🟡",
    "paused": "⚫",
    "blocked": "🟠",
    "failed": "✕",
    "completed": "✓",
    "cancelled": "✕",
    "draft": "🌱",
}


def mission_glyph(status: str) -> str:
    return MISSION_GLYPHS.get(str(status or "").strip().lower(), "🌱")


def growth_class(status: str, done: int = 0, total: int = 0) -> str:
    """Organic growth state for cards: seed → sprout → grown → bloom.
    Purely presentational; status text stays next to it."""
    key = str(status or "").strip().lower()
    if key in ("completed",):
        return "growth-bloom"
    if key in ("failed", "blocked", "cancelled"):
        return "growth-seed"
    try:
        if total > 0 and done >= total:
            return "growth-bloom"
        if total > 0 and done > 0:
            return "growth-grown"
    except TypeError:
        pass
    if key in ("running", "approved"):
        return "growth-sprout"
    return "growth-seed"


def empty(text: str = "Nothing here yet.") -> str:
    return f"<p class=\"empty\">{esc(text)}</p>"


def _living_chip_default() -> str:
    """Global living-state indicator for the topbar (BIG #31).

    Exception to the no-fetch rule, deliberately: the indicator is
    global chrome, not page data, and every page must show the same
    state without per-page wiring. Best-effort — an empty string on
    any failure, so a page never breaks on the indicator. Callers
    may still pass `living=` explicitly to override (tests, embeds).

    BIG #40 appends compact presence counts (waiting ·
    discoveries · offline) linking to /presence — same
    best-effort rule, counts vanish (never break) on failure.
    """
    try:
        from .living_state import current_state
        state = current_state()
        base = (f"<span aria-label=\"Mycelium state: "
                f"{esc(state.get('line', ''))}\" role=\"status\">"
                f"{esc(state.get('glyph', ''))} "
                f"{esc(state.get('line', ''))}</span>")
    except Exception:
        return ""
    try:
        from .presence import attention_snapshot
        counts = attention_snapshot(limit=120)["counts"]
        waiting = int(counts.get("needs", 0))
        found = int(counts.get("discovered", 0))
        offline = int(counts.get("offline", 0))
        extra = (f" <span class=\"presence-chip\">· "
                 f"{waiting} waiting · {found} discoveries · "
                 f"{offline} offline "
                 f"<a href=\"/presence\">attention →</a></span>")
    except Exception:
        extra = ""
    return base + extra


def shell(title: str, active: str, main: str, context: str = "",
          command: str = "", living: str | None = None) -> str:
    """Full workshop shell. `main` is the workspace column,
    `context` the right rail, `command` the bottom bar, `living`
    an optional pre-rendered living-state chip for the topbar
    (None = compute the global indicator)."""
    context_html = f"<aside class=\"context\" " \
        f"aria-label=\"Context\">{context}</aside>" if context \
        else ""
    cmd_html = f"<div class=\"cmdbar\">{command}</div>" \
        if command else ""
    living_html = ""
    chip = living if living is not None else _living_chip_default()
    if chip:
        living_html = f"<span class=\"ext\">{chip}</span>"
    return f"""<!doctype html><html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(title)} — Mycelium Living Workshop</title>
<style>{BASE_CSS}</style></head>
<body><div class="shell">
<header class="topbar"><span class="brand">MYCELIUM <small>living workshop · local-first</small></span><span class="spacer"></span>{living_html}<a class="ext" href="http://127.0.0.1:8080" target="_blank" rel="noopener">INVENTory :8080</a> <a class="ext" href="/api/v1/agent/status">agent JSON</a></header>
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


# -- BIG #33 living world helpers ---------------------------------------------
# Presentational only: technical state text always stays next to
# the visual. Growth vocabulary (seed/sprout/growing/bloom/
# harvest) never replaces backend status.

GROWTH_STAGES = ("seed", "sprout", "growing", "bloom", "harvest")

LIVING_BG_JS = """
(function(){
try{
if (window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;
var c = document.getElementById('living-canvas');
if (!c) return;
var x = c.getContext('2d');
function size(){ c.width = window.innerWidth; c.height = window.innerHeight; }
size();
window.addEventListener('resize', size);
var density = parseInt(c.getAttribute('data-spores') || '26', 10);
if (!(density >= 8 && density <= 48)) density = 26;
var waiting = c.getAttribute('data-waiting') === '1';
var onlineNodes = parseInt(c.getAttribute('data-nodes') || '0', 10);
if (!(onlineNodes >= 0 && onlineNodes <= 30)) onlineNodes = 0;
var tempo = 1 + Math.min(onlineNodes, 6) * 0.08;
var spores = [];
for (var i = 0; i < density; i++) spores.push({x: Math.random(), y: Math.random(), r: 1 + Math.random() * 2, s: .0002 + Math.random() * .0006, o: .15 + Math.random() * .3});
var pulse = 0;
function frame(){
pulse += .008 * tempo;
x.clearRect(0, 0, c.width, c.height);
for (var i = 0; i < spores.length; i++){
var p = spores[i];
p.y -= p.s * tempo;
if (p.y < -0.02) { p.y = 1.02; p.x = Math.random(); }
var px = p.x * c.width + Math.sin(pulse + i) * 8;
var py = p.y * c.height;
x.beginPath();
x.arc(px, py, p.r, 0, 6.283);
var amber = waiting && (i % 5 === 0);
x.fillStyle = amber ? 'rgba(217,164,65,' + p.o.toFixed(2) + ')' : 'rgba(201,214,107,' + p.o.toFixed(2) + ')';
x.fill();
}
window.requestAnimationFrame(frame);
}
window.requestAnimationFrame(frame);
} catch (e) { /* decorative only */ }
})();
"""


def living_bg() -> str:
    """Subtle drifting-spore canvas. Decorative, reduced-motion safe.

    BIG #35: density follows recent ecosystem activity (more
    events = more spores, 8..48) and every fifth spore glows
    amber while approvals wait. BIG #41: drift tempo rises
    slightly with online nodes (capped +48%). Ambient only —
    motion never claims specific events happened."""
    spores = 26
    waiting = False
    online_nodes = 0
    try:
        from .living_state import current_state
        state = current_state()
        activity = int(state.get("new_observations_24h", 0)) + \
            int(state.get("new_candidates_24h", 0)) + \
            int(state.get("new_connections_24h", 0)) + \
            int(state.get("running_missions", 0)) + \
            int(state.get("active_research_runs", 0)) + \
            int(state.get("automation_running", 0)) + \
            int(state.get("automation_waiting", 0))
        spores = max(8, min(48, 16 + activity * 2))
        waiting = int(state.get("waiting_approvals", 0)) > 0
        online_nodes = max(0, min(30, int(
            state.get("online_nodes", 0))))
    except Exception:
        pass
    return ('<div class="living-bg" aria-hidden="true"></div>'
            '<canvas id="living-canvas" class="living-canvas" '
            f'data-spores="{spores}" '
            f'data-waiting="{1 if waiting else 0}" '
            f'data-nodes="{online_nodes}" '
            'aria-hidden="true"></canvas>'
            f'<script>{LIVING_BG_JS}</script>')


def visual_state(state: str) -> str:
    """State language chip: REAL solid, TEST/SIMULATED dashed,
    UNAVAILABLE muted, WAITING amber, ACTIVE living, BLOCKED
    contained, VERIFIED glow, CANDIDATE sprout, OBSERVATION
    spore. The exact technical state stays as text."""
    key = str(state or "unknown").strip().upper().replace(" ", "_")
    known = {"REAL", "TEST", "SIMULATED", "UNAVAILABLE", "WAITING",
             "ACTIVE", "BLOCKED", "VERIFIED", "CANDIDATE",
             "OBSERVATION"}
    css = key if key in known else "OBSERVATION"
    return f"<span class=\"chip state-{esc(css.lower())}\">{esc(key)}</span>"


def growth_bar(stage: str, label: str = "") -> str:
    """Organic progress: seed — sprout — growing — bloom — harvest."""
    key = str(stage or "seed").strip().lower()
    try:
        level = GROWTH_STAGES.index(key) + 1
    except ValueError:
        level, key = 1, "seed"
    glyphs = "🌱—🌿—🌳" if level < 4 else "🌱—🌿—🌳✿"
    bars = "".join(
        f"<span class=\"g{' on' if i < level else ''}\"></span>"
        for i in range(5))
    caption = esc(label or key)
    return (f"<div class=\"growthbar\" role=\"img\" aria-label=\"Growth: {caption}\">"
            f"<span aria-hidden=\"true\">{glyphs}</span>{bars}"
            f"<small class=\"muted\">{caption}</small></div>")


def quest_steps(steps: list) -> str:
    """Mission steps as a quest trail: ✓ done, ● now, ○ open.
    Backend status text is kept per step."""
    rows = []
    for step in steps or []:
        status = str(step.get("status", step.get("state", "open")))
        text = str(step.get("description", step.get("title", status)))[:120]
        key = status.strip().lower()
        if key in ("done", "completed", "verified", "succeeded"):
            rows.append(f"<li><span class=\"q-done\">✓</span> {esc(text)} "
                        f"<span class=\"muted\">[{esc(status)}]</span></li>")
        elif key in ("running", "active", "in_progress", "now"):
            rows.append(f"<li><span class=\"q-now\">●</span> {esc(text)} "
                        f"<span class=\"muted\">[{esc(status)}]</span></li>")
        elif key in ("blocked", "failed", "paused"):
            rows.append(f"<li><span class=\"q-now\">■</span> {esc(text)} "
                        f"<span class=\"muted\">[{esc(status)}]</span></li>")
        else:
            rows.append(f"<li><span class=\"q-todo\">○</span> {esc(text)} "
                        f"<span class=\"muted\">[{esc(status)}]</span></li>")
    return f"<ul class=\"quest\"> {''.join(rows) or '<li>○ No steps yet.</li>'} </ul>"


def symbiosis_chip(state: str) -> str:
    key = str(state or "").strip().upper()
    if key not in ("PROPOSED", "SUPPORTED", "VERIFIED"):
        key = "PROPOSED"
    return f"<span class=\"chip sym-{esc(key)}\">{esc(key)}</span>"


#: Stage states that count as done for progress bars. Everything
#: else counts as open; blocked/failed show separately. Callers
#: pass real backend states — this helper only renders.
PROGRESS_DONE = frozenset({
    "done", "completed", "verified", "approved", "prepared",
    "sliced", "gcode-ready", "printed-simulated", "observed",
    "connected", "inspected",
})

PROGRESS_BAD = frozenset({"blocked", "failed", "cancelled",
                          "rejected"})


def stage_progress(title: str, stages: list) -> str:
    """Real progress from real stages: [██████░░░░] 60% plus a
    ✓/○/■ checklist with backend state text. No XP, no levels —
    the bar derives from the stages passed in."""
    items = list(stages or [])
    total = len(items)
    done = sum(1 for label, state in items
               if str(state).strip().lower() in PROGRESS_DONE)
    percent = int(100 * done / total) if total else 0
    filled = max(0, min(10, round(10 * done / total))) if total \
        else 0
    bar = "█" * filled + "░" * (10 - filled)
    rows = []
    for label, state in items:
        key = str(state).strip().lower()
        if key in PROGRESS_DONE:
            mark = "<span class=\"q-done\">✓</span>"
        elif key in PROGRESS_BAD:
            mark = "<span class=\"q-now\">■</span>"
        else:
            mark = "<span class=\"q-todo\">○</span>"
        rows.append(f"<li>{mark} {esc(label)} "
                    f"<span class=\"muted\">[{esc(state)}]</span></li>")
    return (
        f"<div class=\"panel\"><h3>{esc(title)}</h3>"
        f"<p role=\"img\" aria-label=\"{esc(title)}: {percent}%\">"
        f"<code>[{bar}] {percent}%</code></p>"
        f"<ul class=\"quest\">{''.join(rows) or '<li>No stages.</li>'}</ul>"
        f"</div>")


def guide_card(item: dict) -> str:
    kind = str(item.get("kind", ""))
    nxt = item.get("next", {}) if isinstance(item.get("next"), dict) else {}
    after = str(item.get("after", ""))
    afterwards = (f"<br><small class=\"muted\">Afterwards: "
                  f"{esc(after)}</small>" if after else "")
    return (f"<div class=\"sprout guide-card kind-{esc(kind)}\">"
            f"<b>{esc(item.get('glyph', '🌱'))} "
            f"{esc(item.get('what', ''))}</b><br>"
            f"<small>{esc(item.get('why', ''))}</small><br>"
            f"<a href=\"{esc(nxt.get('href', '/'))}\">"
            f"{esc(nxt.get('label', 'Open'))} →</a>"
            f"{afterwards}</div>")


def presence_card(item: dict) -> str:
    """One attention card: WHAT / WHY / SOURCE / NEXT + actions.

    All text escaped here at the render boundary. YES/NO reuse
    the exact form mechanics of the approval gates (response
    field for desktop/write decisions, path-bound mission
    endpoints); everything else offers OPEN + DEFER only.
    DEFER posts the item id to the presence triage endpoint and
    performs nothing.
    """
    band = str(item.get("band", "discovered"))
    kind = str(item.get("type", ""))
    action = item.get("action", {}) if isinstance(
        item.get("action"), dict) else {}
    yes_href = esc(str((action.get("YES", {}) or {}).get(
        "href", "")))
    no_href = esc(str((action.get("NO", {}) or {}).get(
        "href", "")))
    buttons: list[str] = []
    if kind in ("approval_desktop", "approval_write") and \
            yes_href and no_href:
        buttons.append(
            f"<form method=\"post\" action=\"{yes_href}\" "
            f"style=\"display:inline\">"
            f"<input type=\"hidden\" name=\"response\" "
            f"value=\"YES\"><button type=\"submit\">YES"
            f"</button></form>")
        buttons.append(
            f"<form method=\"post\" action=\"{no_href}\" "
            f"style=\"display:inline\">"
            f"<input type=\"hidden\" name=\"response\" "
            f"value=\"NO\"><button type=\"submit\">NO"
            f"</button></form>")
    elif kind == "approval_mission" and yes_href and no_href:
        buttons.append(
            f"<form method=\"post\" action=\"{yes_href}\" "
            f"style=\"display:inline\">"
            f"<button type=\"submit\">YES, doorgaan</button>"
            f"</form>")
        buttons.append(
            f"<form method=\"post\" action=\"{no_href}\" "
            f"style=\"display:inline\">"
            f"<button type=\"submit\">Cancel plan</button>"
            f"</form>")
    open_href = esc(str(item.get("open_href", "/activity")))
    buttons.append(f"<a class=\"chip\" href=\"{open_href}\">"
                   f"OPEN</a>")
    buttons.append(
        f"<form method=\"post\" "
        f"action=\"/web/presence/defer\" "
        f"style=\"display:inline\">"
        f"<input type=\"hidden\" name=\"item_id\" "
        f"value=\"{esc(item.get('id', ''))}\">"
        f"<button type=\"submit\" title=\"Nothing changes; "
        f"decide later\">DEFER</button></form>")
    why_points = "".join(
        f"<li><small>{esc(reason)}</small></li>"
        for reason in (item.get("priority_reasons", []) or [])[:4])
    return (f"<div class=\"sprout band-{esc(band)}\">"
            f"<b>{esc(item.get('title', ''))}</b> "
            f"{chip(esc(item.get('status', 'NEW')))}<br>"
            f"<small><b>WHY:</b> {esc(item.get('reason', ''))}"
            f"</small><br>"
            f"<small class=\"muted\">SOURCE: "
            f"{esc(item.get('source', ''))}</small><br>"
            f"<small class=\"muted\">NEXT: "
            f"<a href=\"{open_href}\">Open →</a></small>"
            f"<ul class=\"quest\">{why_points}</ul>"
            f"<p>{' '.join(buttons)}</p></div>")


def empty_grove(text: str, actions: list | None = None) -> str:
    """Empty state with a small mycelium character, never a void."""
    links = "".join(
        f"<a class=\"chip\" href=\"{esc(href)}\">{esc(label)}</a>"
        for label, href in (actions or []))
    return (f"<div class=\"panel empty-hero\"><div class=\"sprout-char\" "
            f"aria-hidden=\"true\">🌱</div><p>{esc(text)}</p>"
            f"<p class=\"flowline\">{links}</p></div>")


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
    `data_json` is the already-serialized graph dict. An
    empty graph renders guidance plus a static mycelium
    figure (decorative, aria-hidden) instead of a void."""
    import json as _json
    safe_data = data_json.replace("</", "<\\/")
    try:
        node_count = len(_json.loads(data_json).get("nodes",
                                                    []))
    except ValueError:
        node_count = -1
    empty_html = ""
    if node_count == 0:
        empty_html = """<div class="panel"><h2>A quiet patch of soil</h2>
<p class="muted">Nothing grows here yet. Pick a seed above, open a project, or check that INVENTory is running — the graph only ever shows real data.</p>
<p><a href="/projects">Browse projects</a> · <a href="/memory">Browse memory</a></p>
<svg viewBox="0 0 400 120" width="100%" height="120" aria-hidden="true">
<g fill="none" stroke="var(--fern)" stroke-width="1.5" opacity=".55">
<path d="M20 100 C 90 90, 120 60, 200 62 S 330 40, 385 55"/>
<path d="M200 62 C 190 40, 170 30, 150 28"/>
<path d="M200 62 C 220 45, 250 42, 275 30"/>
<path d="M90 92 C 80 75, 60 70, 45 60"/>
<circle cx="150" cy="28" r="3.5" fill="var(--moss)" stroke="none" opacity=".8"/>
<circle cx="275" cy="30" r="3.5" fill="var(--spore)" stroke="none" opacity=".8"/>
<circle cx="45" cy="60" r="3" fill="var(--moss)" stroke="none" opacity=".7"/>
<circle cx="385" cy="55" r="2.5" fill="var(--ink-faint)" stroke="none" opacity=".7"/>
</g></svg></div>"""
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
{empty_html}
<div class="panel"><h2>Details</h2><div id="wdetails">Select a node or relation. Keyboard: Tab to a node, Enter to open.</div></div>
<script>const WGDATA = {safe_data};
{GRAPH_JS.replace("constWGDATA;", "")}</script>"""

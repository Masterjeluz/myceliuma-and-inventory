from pathlib import Path
from flask import Flask, render_template_string, redirect
import json
import subprocess
import sys
from datetime import datetime

app = Flask(__name__)

BASE = Path(__file__).parent
DISCOVERY = BASE / "discovery.json"
INDEX = BASE / "project_index.json"
AGENT = BASE / "agent.py"

HTML = """
<!doctype html>
<html>
<head>
<meta charset=\"utf-8\">
<title>Mycelium Desktop Agent</title>
<style>
body {font-family: system-ui, sans-serif; max-width: 1200px; margin: 30px auto; padding: 0 20px; background: #101410; color: #ece7d8;}
h1 {margin-bottom: 5px; color: #ece7d8;}
a {color: #a5c48a;}
.stats {display: flex; gap: 12px; flex-wrap: wrap; margin: 20px 0;}
.stat {background: #1b221b; border: 1px solid #2e3a2c; border-radius: 10px; padding: 15px 20px;}
.card {background: #1b221b; border: 1px solid #2e3a2c; border-radius: 10px; padding: 16px; margin: 12px 0;}
.path {font-family: monospace; word-break: break-all; margin-bottom: 10px;}
.badge {display: inline-block; padding: 4px 8px; margin: 2px; border-radius: 6px; background: #222b22; border: 1px solid #2e3a2c; font-size: 13px;}
.git {background: #22301f; border-color: #4c6b4f;}
.warn {background: #2b2416; border-color: #8a6a2c;}
.info {background: #1b2430; border-color: #3a4a5a;}
button {padding: 10px 18px; border: 1px solid #2e3a2c; border-radius: 8px; cursor: pointer; font-size: 15px; background: #4c6b4f; color: #ece7d8;}
button:focus-visible {outline: 2px solid #d9a441; outline-offset: 2px;}
button:hover {opacity: .85;}
.meta {color: #8a9184; font-size: 13px;}
</style>
</head>
<body>
<h1>🧠 Mycelium Desktop Agent</h1>
<p class=\"meta\">Lokale computer-agent • read-only discovery</p>
<div class=\"stats\">
  <div class=\"stat\">💻 <b>{{ computer }}</b><br><span class=\"meta\">Computer</span></div>
  <div class=\"stat\">📁 <b>{{ projects|length }}</b><br><span class=\"meta\">Projectlocaties</span></div>
  <div class=\"stat\">🟢 <b>{{ git_count }}</b><br><span class=\"meta\">Git-projecten</span></div>
</div>
<form action=\"/scan\" method=\"post\"><button>🔄 Computer opnieuw scannen</button></form>
<h2>Projecten</h2>
{% if projects %}
{% for project in projects %}
<div class=\"card\">
  <div class=\"path\">📂 {{ project.name or project.path }}</div>
  <div class=\"path\">{{ project.path }}</div>
  {% for t in project.types %}<span class=\"badge\">{{ t }}</span>{% endfor %}
  {% if project.git %}<span class=\"badge git\">🟢 Git repository</span>{% else %}<span class=\"badge\">⚪ Geen Git</span>{% endif %}
  {% if project.stable_id %}<span class=\"badge info\" title=\"Stable ID (computer + path)\">🆔 {{ project.stable_id[:12] }}…</span>{% endif %}
  {% if project.is_backup_copy %}<span class=\"badge warn\">💾 Mogelijke backup/kopie</span>{% endif %}
  {% if project.is_nested %}<span class=\"badge info\">📦 Nested repository</span>{% endif %}
  {% if project.parent_id %}<span class=\"badge info\">📦 Onderdeel van geïndexeerd project</span>{% endif %}
  {% if project.nested_children %}<span class=\"badge info\">📦 {{ project.nested_children|length }} nested project(en)</span>{% endif %}
  {% if project.possible_copies %}<span class=\"badge warn\">👯 {{ project.possible_copies|length }} mogelijke kopie(ën)</span>{% endif %}
  {% if project.duplicate_group %}<span class=\"badge warn\">👯 Dubbele locatie ({{ project.duplicate_candidates|length + 1 }}x)</span>{% endif %}
  <p class=\"meta\">{% if project.git_remote %}🔗 {{ project.git_remote }}<br>{% endif %}{% if project.last_modified %}🕒 {{ project.last_modified }}<br>{% endif %}{% if project.file_count is not none %}📄 {{ project.file_count }} bestanden<br>{% endif %}{% if project.recognized_files %}🧩 {{ project.recognized_files|join(', ') }}<br>{% endif %}{% if project.is_nested and project.parent_project %}📦 Onderdeel van: {{ project.parent_project }}<br>{% endif %}{% if project.duplicate_candidates %}👯 Ook gevonden in: {{ project.duplicate_candidates|join('; ') }}<br>{% endif %}{% if project.same_remote_candidates %}🔗 Zelfde remote elders: {{ project.same_remote_candidates|join('; ') }}{% endif %}</p>
</div>
{% endfor %}
{% else %}
<div class=\"card\">Geen projecten gevonden.</div>
{% endif %}
<hr>
<p class=\"meta\">Laatste scan: {{ timestamp }}</p>
</body>
</html>
"""
def load_discovery():
    if not DISCOVERY.exists():
        return {"computer": "unknown", "projects": [], "timestamp": "nooit"}
    return json.loads(DISCOVERY.read_text(encoding="utf-8"))


def load_relations():
    """Stable IDs + relations from project_index.json, keyed by path.

    Best-effort: missing or invalid index means no relation badges,
    never a broken page. The index only ever derives from our own
    discovery.json (see project_index.py)."""
    try:
        if not INDEX.exists():
            return {}
        index = json.loads(INDEX.read_text(encoding="utf-8"))
        by_path = {}
        for entry in index.get("projects", []):
            if not isinstance(entry, dict):
                continue
            path = entry.get("path")
            if not isinstance(path, str):
                continue
            relations = entry.get("relations", {}) or {}
            by_path[path] = {
                "stable_id": entry.get("id", ""),
                "parent_id": relations.get("parent_id"),
                "nested_children": relations.get("nested_children_ids", []) or [],
                "possible_copies": relations.get("possible_copy_ids", []) or [],
            }
        return by_path
    except Exception:
        return {}


@app.route("/")
def index():
    data = load_discovery()
    raw_projects = data.get("projects", [])
    relations = load_relations()
    projects = []
    for project in raw_projects:
        merged = dict(project)
        info = relations.get(project.get("path", ""))
        if info:
            merged.update(info)
        else:
            merged.setdefault("stable_id", "")
            merged.setdefault("parent_id", None)
            merged.setdefault("nested_children", [])
            merged.setdefault("possible_copies", [])
        projects.append(merged)
    return render_template_string(HTML, computer=data.get("computer", "unknown"), projects=projects, git_count=sum(1 for p in projects if p.get("git")), timestamp=data.get("timestamp", "onbekend"))


@app.post("/scan")
def scan():
    subprocess.run([sys.executable, str(AGENT)], check=True)
    try:
        # Keep relations fresh: the index purely derives from the
        # discovery.json just written. Best-effort, never fails scan.
        subprocess.run([sys.executable, "-c",
                        "import project_index; project_index.main()"],
                       check=False, cwd=str(BASE))
    except Exception:
        pass
    return redirect("/")
if __name__ == "__main__":
    app.run(host="127.0.0.1", port=8787, debug=False)

from pathlib import Path
from flask import Flask, render_template_string, redirect
import json
import subprocess
import sys
from datetime import datetime

app = Flask(__name__)

BASE = Path(__file__).parent
DISCOVERY = BASE / "discovery.json"
AGENT = BASE / "agent.py"

HTML = """
<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>Mycelium Desktop Agent</title>
<style>
body {
    font-family: system-ui, sans-serif;
    max-width: 1200px;
    margin: 30px auto;
    padding: 0 20px;
    background: #f5f6f8;
    color: #222;
}
h1 { margin-bottom: 5px; }
.stats {
    display: flex;
    gap: 12px;
    flex-wrap: wrap;
    margin: 20px 0;
}
.stat {
    background: white;
    border: 1px solid #ddd;
    border-radius: 10px;
    padding: 15px 20px;
}
.card {
    background: white;
    border: 1px solid #ddd;
    border-radius: 10px;
    padding: 16px;
    margin: 12px 0;
}
.path {
    font-family: monospace;
    word-break: break-all;
    margin-bottom: 10px;
}
.badge {
    display: inline-block;
    padding: 4px 8px;
    margin: 2px;
    border-radius: 6px;
    background: #eee;
    font-size: 13px;
}
.git {
    background: #dff5df;
}
.warn {
    background: #fff3cd;
}
.info {
    background: #e7f1ff;
}
button {
    padding: 10px 18px;
    border: 0;
    border-radius: 8px;
    cursor: pointer;
    font-size: 15px;
}
button:hover {
    opacity: .85;
}
.meta {
    color: #666;
    font-size: 13px;
}
</style>
</head>

<body>

<h1>🧠 Mycelium Desktop Agent</h1>
<p class="meta">
    Lokale computer-agent • read-only discovery
</p>

<div class="stats">
    <div class="stat">
        💻 <b>{{ computer }}</b>
        <br><span class="meta">Computer</span>
    </div>

    <div class="stat">
        📁 <b>{{ projects|length }}</b>
        <br><span class="meta">Projectlocaties</span>
    </div>

    <div class="stat">
        🟢 <b>{{ git_count }}</b>
        <br><span class="meta">Git-projecten</span>
    </div>
</div>

<form action="/scan" method="post">
    <button>🔄 Computer opnieuw scannen</button>
</form>

<h2>Projecten</h2>

{% if projects %}

{% for project in projects %}
<div class="card">

    <div class="path">
        📂 {{ project.name or project.path }}
    </div>
    <div class="path">{{ project.path }}</div>

    {% for t in project.types %}
        <span class="badge">{{ t }}</span>
    {% endfor %}

    {% if project.git %}
        <span class="badge git">🟢 Git repository</span>
    {% else %}
        <span class="badge">⚪ Geen Git</span>
    {% endif %}

    {% if project.is_backup_copy %}
        <span class="badge warn">💾 Mogelijke backup/kopie</span>
    {% endif %}

    {% if project.is_nested %}
        <span class="badge info">📦 Nested repository</span>
    {% endif %}

    {% if project.duplicate_group %}
        <span class="badge warn">👯 Dubbele locatie ({{ project.duplicate_candidates|length + 1 }}x)</span>
    {% endif %}

    <p class="meta">
        {% if project.git_remote %}🔗 {{ project.git_remote }}<br>{% endif %}
        {% if project.last_modified %}🕒 {{ project.last_modified }}<br>{% endif %}
        {% if project.file_count is not none %}📄 {{ project.file_count }} bestanden<br>{% endif %}
        {% if project.recognized_files %}🧩 {{ project.recognized_files|join(', ') }}<br>{% endif %}
        {% if project.is_nested and project.parent_project %}📦 Onderdeel van: {{ project.parent_project }}<br>{% endif %}
        {% if project.duplicate_candidates %}👯 Ook gevonden in: {{ project.duplicate_candidates|join('; ') }}<br>{% endif %}
        {% if project.same_remote_candidates %}🔗 Zelfde remote elders: {{ project.same_remote_candidates|join('; ') }}{% endif %}
    </p>

</div>
{% endfor %}

{% else %}

<div class="card">
    Geen projecten gevonden.
</div>

{% endif %}

<hr>

<p class="meta">
    Laatste scan:
    {{ timestamp }}
</p>

</body>
</html>
"""

def load_discovery():
    if not DISCOVERY.exists():
        return {
            "computer": "unknown",
            "projects": [],
            "timestamp": "nooit"
        }

    return json.loads(
        DISCOVERY.read_text(encoding="utf-8")
    )


@app.route("/")
def index():
    data = load_discovery()

    projects = data.get("projects", [])

    return render_template_string(
        HTML,
        computer=data.get("computer", "unknown"),
        projects=projects,
        git_count=sum(1 for p in projects if p.get("git")),
        timestamp=data.get("timestamp", "onbekend")
    )


@app.post("/scan")
def scan():
    subprocess.run(
        [sys.executable, str(AGENT)],
        check=True
    )

    return redirect("/")


if __name__ == "__main__":
    app.run(
        host="127.0.0.1",
        port=8787,
        debug=False
    )

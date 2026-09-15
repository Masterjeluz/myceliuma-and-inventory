# INVENTory

Een local-first wereldmodel-, geheugen- en herkomstsysteem voor de fysieke, digitale en mogelijk mentale werkplaats.

INVENTory houdt bij **wat er is en wat er gebeurt**: objecten, materialen, gereedschappen, machines, projecten, ideeën, bestanden, en relaties.

> **Status:** Milestone 1B — Objecten + Projecten + Ideeën + Relaties + Events.  
> Milestone 1A (Fundament & Fysieke Objecten) is afgerond en blijft de basis.  
> Dit is een zelfstandig project dat volledig losstaat van de Mycelium AI database en codebase.

---

## Wat werkt (Milestones 1A + 1B)

### Milestone 1A — Fundament & Fysieke Objecten

- **Zelfstandige SQLite database** met **WAL-modus** (`PRAGMA journal_mode=WAL`) en connectie-timeouts.
- **Stabiele identifiers** met prefix `obj_...` (bijv. `obj_0192e8a1f4b8c9d2`).
- **Ingebouwd Provenance-fundament**:
  - Bronnen: `user-created`, `imported`, `ai-generated`, `sensor-observed`, `external-source`.
  - Strikte regel: AI-observaties zijn standaard **ongeverifieerd** (`human_verified = False`) totdat een mens ze bevestigt.
- **Object CRUD API**:
  - `GET /api/v1/health`
  - `GET /api/v1/objects`
  - `GET /api/v1/objects/{id}`
  - `POST /api/v1/objects`
  - `PATCH /api/v1/objects/{id}`
  - `DELETE /api/v1/objects/{id}`
- **Server-rendered Web UI**:
  - Overzichtstabel op `http://127.0.0.1:8080/` met herkomst-badges (`🤖 AI (unverified)`, `👤 User`, etc.).
  - Webformulier om direct nieuwe objecten in te voeren.
  - Detailpagina op `http://127.0.0.1:8080/objects/{id}` met volledige provenance-historie en ruwe JSON.
- **Geautomatiseerde testsuite** (`pytest`): 35 tests in 3 bestanden
  (`test_database.py`, `test_objects.py`, `test_milestone_1b.py`).
  Alleen dit reproduceerbare aantal geldt; oudere "73 tests"-claims zijn niet
  reproduceerbaar en worden nergens meer gesteld.

### Milestone 1B — Projecten, Ideeën, Relaties, Events (geïmplementeerd)

- **Project CRUD API** (`proj_...`-IDs, status `idea…archived`):
  - `GET /api/v1/projects`
  - `POST /api/v1/projects`
  - `GET /api/v1/projects/{id}`
  - `PATCH /api/v1/projects/{id}`
  - `DELETE /api/v1/projects/{id}`
- **Idea CRUD API** (`idea_...`-IDs, status `raw…converted`): zelfde vijf routes
  onder `/api/v1/ideas`.
- **Relationship API** (`rel_...`-IDs, 10 predicaten o.a. `used_in`, `part_of`,
  `contains`, `became`, `led_to`, `depends_on`, `produced_by`, `stored_in`;
  geen zelfreferentie):
  - `GET /api/v1/relationships`
  - `POST /api/v1/relationships`
  - `DELETE /api/v1/relationships/{id}`
- **Event-stream** (alleen lezen): `GET /api/v1/events` — registreert alle
  CRUD-overgangen met `entity_id`, timestamp en provenance.
- **Web UI-uitbreiding**: overzicht- en detailpagina's voor projecten en ideeën
  (`/projects`, `/projects/{id}`, `/ideas`, `/ideas/{id}`) plus relatiebeheer
  op de detailpagina's.

---

## Snel Starten

### 1. Open de map `inventory` in een terminal

```powershell
cd inventory
```

### 2. Maak en activeer een virtuele omgeving

#### Windows PowerShell:
```powershell
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
```

#### Linux / macOS:
```bash
python3 -m venv .venv
source .venv/bin/activate
```

### 3. Installeer INVENTory (inclusief dev-dependencies voor tests)

```bash
pip install -e ".[dev]"
```

### 4. Start de INVENTory server

```bash
python -m uvicorn app.main:app --host 127.0.0.1 --port 8080 --reload
```

Open daarna je browser op:
- **Web UI:** `http://127.0.0.1:8080/`
- **Interactieve API Docs:** `http://127.0.0.1:8080/docs`

---

## Tests Uitvoeren

Run de complete testsuite vanuit de `inventory`-map:

```bash
pytest -v
```

---

## Wat is bewust nog NIET gebouwd (Toekomstige Milestones)

- **Milestone 3:** Conversations (geheugen) en Files (lokale media-opslag met SHA-256).
- **Milestone 4:** Full-text search (SQLite FTS5) en graaf-navigatie in de webinterface.
- **Milestone 5:** Eerste Mycelium AI ↔ INVENTory REST-koppeling (automatische hardware-inventarisatie van nodes).
- **Expliciet ontbrekende entiteiten** (alleen als `Object`-tekst of predicaat
  benaderbaar, niet als eigen entiteit; toevoeging pas via architectuurcontract):
  hardware, sensor, camera, materiaal, locatie, AI-model, taak, observatie-tabel.

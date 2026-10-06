# myceliuma-and-inventory

Persoonlijke, lokale AI-infrastructuur: **Mycelium AI** (de denkende,
coördinerende laag) boven **INVENTory** (het persistente wereldmodel
van spullen, projecten en ideeën).

- `mycelium-ai-main/` — Mycelium-coordinator (`:8000`), desktop-agent,
  node-client, providers, missies. Zie de [README](mycelium-ai-main/README.md).
- `inventory/` — INVENTory-wereldmodel (`:8080`, FastAPI + SQLite).
  Onafhankelijk gebied; Mycelium leest het alleen via een read-only
  bridge (nooit gedeelde database, nooit cross-imports).
- `Mycelium/agent/` — lokale desktop-scanner (projectdetectie, UI
  `:8787`). Alleen-lezen richting gebruikersprojecten.

## Werkende keten (live bewezen)

Chat → context → advies → missie → approval → stap → taak →
desktop-agent → observatie → volgende stap → gesprekupdate.

Mycelium redeneert en coördineert; de desktop-agent bedient
scherm/muis/toetsenbord pas na expliciete menselijke goedkeuring;
INVENTory onthoudt de wereld; Ollama/Qwen adviseert lokaal.

## Snel starten

Zie [mycelium-ai-main/README.md](mycelium-ai-main/README.md) (coordinator
+ node) en [docs/ROADMAP.md](mycelium-ai-main/docs/ROADMAP.md) (richting).
Verificatie per gebied: `pytest -v` in `mycelium-ai-main/` (1953 tests,
173 files) en `inventory/` (183 tests, 13 files), telling 2026-10-06 via
`def test_`. Oudere "822/178"-zinnen hieronder zijn vervallen.
Teststrategie (FAST/FEATURE/FULL): zie [docs/TESTING.md](docs/TESTING.md);
actuele kaart: [docs/CURRENT_STATE.md](docs/CURRENT_STATE.md).

## Principes

Local-first · mens beslist (exact YES, geen bypass — behalve de
expliciete TOWN_AUTONOMY-dial voor research.fetch_url/
system_inventory/desktop_screenshot, default uit) ·
fail-closed · provenance altijd · AI-advies is geen waarheid ·
geen shell/RCE · geen permanente autonomie (alleen de dial hierboven) ·
cloud is additief, nooit verplicht.

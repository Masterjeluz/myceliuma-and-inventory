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
Verificatie per gebied: `pytest -v` in `mycelium-ai-main/` (822 passed)
en `inventory/` (178 passed, 1 pre-existing faal op een gitignored
lokale database-grootte).

## Principes

Local-first · mens beslist (exact YES, geen bypass) · fail-closed ·
provenance altijd · AI-advies is geen waarheid · geen shell/RCE ·
geen permanente autonomie · cloud is additief, nooit verplicht.

# Nutrition (BIG #11-15, Phase 2) — IMPLEMENTED

MEAL → INGREDIENT → PORTION → NUTRIENT → DAILY TOTAL →
WEEKLY TREND over an extensible nutrient model (21
nutrients: macros, micros, vegan-critical B12/iron/
iodine/omega-3). No giant hardcoded food database; foods
are user/recipe/label entries with per-100g profiles.

## Rules

- AI may propose values (`ai_proposal` source), but source
  and verification stay visible on every number.
- Vegan-first with explicit evidence: `vegan`/`non_vegan`
  claims require an ingredient/label/source note; a meal
  folds to its weakest claim (unknown beats vegan).
- Coverage answers only adequate/possibly low/possibly
  high/unknown against configurable reference targets,
  always showing source, population/context,
  calculation and uncertainty. Illustrative defaults are
  labelled as such and overridable per call.

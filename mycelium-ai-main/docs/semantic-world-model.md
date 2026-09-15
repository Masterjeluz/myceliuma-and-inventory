# Semantic World Model (BIG #4)

Hoe Mycelium zijn wereld begrijpt vóórdat het handelt: hybride
retrieval over INVENTory, met uitlegbaarheid en een harde grens
tussen feit en advies.

## Stroom

```
query
  ↓
lexical candidates (substring over collecties, bestaande bridge)
  ↓  (+ bounded browse, alleen als semantiek werkt)
semantic scoring (cosine over lokale embeddings, cache met fingerprint)
  ↓
reciprocal-rank fusion (RRF k=60, deterministische tie-break: semantiek wint)
  ↓
relationship expansion (top-5, depth 1|2, bestaande graph-route)
  ↓
provenance-aware context → Mycelium reasoning → missieplanning
```

Modi: **lexical** (altijd beschikbaar, exact het oude substring-
gedrag), **semantic** (alleen embeddings, fail-closed bij afwezig
model), **hybrid** (voorkeur; automatische lexicale fallback).

## Fail-fast probe

Hybrid embedt eerst alleen de query. Mislukt die ene call, dan
degradeert retrieval naar het exacte legacy-pad (alleen search —
geen browse, geen graph). Pas een werkende semantische runtime
ontgrendelt browse-kandidaten en relatie-expansie. Mycelium faalt
dus nooit omdat een embedding-model ontbreekt.

## Embedding-provider

`EmbeddingProvider.embed(texts) -> vectoren`. Alleen lokaal:

- `OllamaEmbeddingProvider`: POST `{loopback}/api/embed` met een
  operator-gekozen model. Loopback-only, timeout ≤ 30s, geen
  credentials. Ontbrekend model → `EmbeddingUnavailable` met een
  `ollama pull`-hint; Mycelium downloadt nooit zelf modellen.
- `UnavailableEmbeddingProvider`: eerlijke afwezigheid, altijd fout.

Geen cloud, geen nieuwe dependencies (stdlib + httpx).

## Storage: afgeleide cache, geen tweede waarheid

Tabel `semantic_vectors` in de chat/agent-database (naast
conversations/missies; queue-database onaangeroerd):

- identiteit = (entity_type, entity_id, **content-fingerprint**,
  model, dim); vector als packed float32-blob.
- fingerprint = sha256(type|id|titel|snippet|provenance-signaal|
  model), herberekend uit het ACTUELE record bij elke lookup.
  Gewijzigde bron → mismatch → miss → opnieuw embedden. Oude
  embeddings worden dus nooit stilzwijgend als actueel gebruikt.
- dim-mismatch (model verwisseld onder dezelfde naam) = miss.
- retentie: laatste 2000 rijen per model; daarboven prune.

## Contextvorming (geen dump)

`hybrid_retrieve()` begrenst: ≤ 60 kandidaten, ≤ 50 resultaten,
expansie top-5, depth 1 (default) of 2. Bestands-inhoud komt er
nooit in; alleen titel/snippet/provenance-signaal. Missies
bewaren de gebruikte records als `context_records` (audit trail).

## FACT vs ADVICE

Elk resultaat draagt `match_type` (semantic/lexical/relationship),
`score` en `why` (ruwe ranks). Scores zijn **ordering-signalen,
geen waarheids-kansen** — dat staat letterlijk in elke `why`.
Provenance en `human_verified` stromen ongewijzigd door, dus een
onzekere AI-observatie kan nooit als feit worden gepresenteerd.
`human_verified=True` komt uitsluitend uit INVENTory-rijen, nooit
uit retrieval of advies.

## Gebruik

- `/advise` en `/chat`: `mode`-parameter (default hybrid),
  response vermeldt `retrieval_mode`, sources bevatten
  `match_type`/`score`.
- Missie-aanmaak (`/chat/{id}/missions`, `/missions/from-template`):
  context via hybrid; retrieval is context, nooit toestemming.
- `/missions/suggest`: onveranderd advies-only.

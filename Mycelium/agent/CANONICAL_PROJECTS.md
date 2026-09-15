# CANONICAL PROJECTS — Milestone 1G

Welke checkout geldt als het actieve systeem, welke zijn kopieën.
Vastgesteld 2026-09-11 op basis van onderzochte Git-remotes (`.git/config`,
alleen gelezen), projectstructuur en naamgeving. Discovery-output blijft alle
locaties vermelden; dit document bepaalt welke telt.

## Canonieke repositories

| Systeem | Canoniek pad | Remote | Stable-ID (index) | Waarom canoniek |
|---|---|---|---|---|
| Desktop Agent | `C:\Users\Jelles\Mycelium\agent` | geen git | — (niet geïndexeerd, eigen laag) | Enige locatie; actieve ontwikkelplek van scanner, index en UI |
| INVENTory | `C:\Users\Jelles\Desktop\Projects\myceliuma-and-inventory\inventory` | `https://github.com/Masterjeluz/inventory2.git` | `03b9d799e59709ca` | Volledige app + tests + `data/`; README onderhouden t/m Milestone 1B |
| Mycelium | `C:\Users\Jelles\Desktop\Projects\myceliuma-and-inventory\mycelium-ai-main` | geen git | `8ee10a747398ed7a` | Volledige structuur (`coordinator/`, `node_client/`, `docs/`, `tests/`) |

## Geneste component (geen apart actief systeem)

| Pad | Remote | Stable-ID | Status |
|---|---|---|---|
| `...\inventory\INVENTory` (genest in canonieke inventory-checkout) | `https://github.com/Masterjeluz/INVENTory.git` | `276515dd2aa12ab2` | Onderdeel van de canonieke checkout; niet als zelfstandig systeem behandelen |

## Bekende kopieën/backups (niet-actief, nooit automatisch samenvoegen)

| Pad | Remote | Stable-ID | Bewijs van kopie |
|---|---|---|---|
| `Documents\Downloads\INVENTory-Milestone-1E-BACKUP` | geen git | `328f09fd7e1cdf1c` | Naam; bevat geneste kopie hieronder |
| `...\INVENTory-Milestone-1E-BACKUP\INVENTory` | `.../INVENTory.git` | `8c0318445b5d4ae7` | Zelfde remote als geneste component |
| `Documents\Downloads\mycelium-ai-main\mycelium-ai-main` | geen git | `d0532bf47c9f40cd` | Dubbele mapnaam (`mycelium-ai-main` in `mycelium-ai-main`), Downloads-locatie |
| `...\mycelium-ai-main\mycelium-ai-main\inventory` | `.../inventory2.git` | `178f2599b076cad1` | Zelfde remote als canonieke INVENTory |
| `...\mycelium-ai-main\mycelium-ai-main\inventory\INVENTory` | `.../INVENTory.git` | `1dacd5fdb2e12b93` | Zelfde remote als geneste component |

Buiten scope (wel ontdekt, geen uitspraak): `Documents\antigravity\wonderful-noether`
(`5b9c32c0163edb07`, git zonder origin) — ongerelateerd project.

## Beleid (bindend)

1. Alleen de canonieke paden gelden als "het systeem" voor ontwikkeling, tests en toekomstige import naar INVENTory.
2. **Gedeelde remote of gedeelde naam ≠ hetzelfde systeem.** Kopieën worden nooit
   automatisch samengevoegd, overschreven of als bron voor synchronisatie gebruikt.
3. Koppeling Desktop→INVENTory verloopt uitsluitend via de mappingtabel
   desktop-`stable_id` ↔ INVENTory-`proj_`-ID (volgende kerninterface, M2B);
   kopie-stable-ID's worden daarin expliciet als `copy_of` gemarkeerd, nooit als
   zelfstandige projecten geïmporteerd.
4. Nieuwe kopie? Toevoegen aan de tabel hierboven, niet aan code.

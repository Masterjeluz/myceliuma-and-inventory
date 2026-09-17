"""Bootstrap research campaign (BIG #28 §26).

On first successful startup after the V1 milestone, Mycelium
creates ONE campaign of read-only research missions over the
known project domains. Properties:

- Idempotent: each mission carries ``metadata.bootstrap_key``
  (``bootstrap:<domain>``); ``ensure_campaign`` skips keys that
  already exist — duplicates are impossible, re-runs are safe.
- Read-only: every mission uses ``investigate_inventory`` /
  ``inspect_project`` steps (readout + analysis) with
  ``safe_autonomy: True, physical: False, write: False,
  external_side_effect: False`` in metadata.
- Honest: missions run only when the research capability is
  actually available (local provider reachable). Otherwise
  they wait and report WAITING_FOR_RESEARCH_CAPABILITY —
  completion is never faked.

Domains (§12): mycelium-arch, inventory, camper, umz, ozfk,
printing-3d, led-costume, solarpunk-workshop, personal-ai.
"""

BOOTSTRAP_DOMAINS = [
    {"key": "bootstrap:mycelium-arch", "domain": "Mycelium AI",
     "template": "inspect_project",
     "goal": "Onderzoek de Mycelium-architectuur: huidige opzet, "
             "resterende technische risico's en nuttige open-source "
             "patronen voor lokale autonome agents.",
     "scope": "architectuur, agent-loops, duurzame missies, "
              "model-routing, safe computer-use"},
    {"key": "bootstrap:inventory", "domain": "INVENTory",
     "template": "investigate_inventory",
     "goal": "Onderzoek INVENTory als wereldmodel: ontologie, "
             "relatiegrafen, provenance en lokale VLM-pijplijnen "
             "voor objectherkenning.",
     "scope": "wereldmodel, provenance, camera-ingestie, "
              "3D-metadata"},
    {"key": "bootstrap:camper", "domain": "Camper (1990)",
     "template": "investigate_inventory",
     "goal": "Onderzoek de camper (1990): renovatieplanning, "
             "onderhoudschecklist, distributieriem, lekkage, luifel, "
             "interieur en 12V/230V-architectuur. Alleen onderzoek; "
             "veiligheidskritisch werk markeren voor menselijke review.",
     "scope": "renovatie, onderhoud, elektra; geen aankopen, "
              "geen gevaarlijke instructies als geverifieerd"},
    {"key": "bootstrap:umz", "domain": "Urban Movement Zeeland",
     "template": "investigate_inventory",
     "goal": "Onderzoek Urban Movement Zeeland: lesplanning, "
             "trainingsprogressie, workshop-ideeën en community-groei. "
             "Geen outreach of boekingen.",
     "scope": "freerunning-lessen, events, community"},
    {"key": "bootstrap:ozfk", "domain": "OZFK",
     "template": "investigate_inventory",
     "goal": "Onderzoek OZFK: competitiestructuur, scoring, "
             "veiligheid, deelnemersflow en februar-eventplanning. "
             "Niemand automatisch contacteren.",
     "scope": "competitie, veiligheid, planning"},
    {"key": "bootstrap:printing-3d", "domain": "3D-printen",
     "template": "investigate_inventory",
     "goal": "Onderzoek 3D-printen voor de workshop (richting "
             "Bambu Lab A1 Mini + AMS Lite, ~€650 budget): "
             "printerlandschap, materialen, CAD→slicer→printer "
             "pijplijnen en camera-verificatie. Niets kopen.",
     "scope": "printers, materialen, lokale AI-workflows"},
    {"key": "bootstrap:led-costume", "domain": "LED-kostuum",
     "template": "investigate_inventory",
     "goal": "Onderzoek het LED-kostuum (WS2812B, 5m, 60 LEDs/m, "
             "300 LEDs, Arduino Nano Every, datapin 6): "
             "stroomverdeling, injectie, thermiek, animatie- "
             "architectuur en batterijveiligheid. Niets bouwen "
             "of inschakelen.",
     "scope": "power, thermiek, wearables, veiligheid"},
    {"key": "bootstrap:solarpunk-workshop", "domain": "SolarPunk workshop",
     "template": "inspect_project",
     "goal": "Onderzoek de SolarPunk-workshop: local-first "
             "werkplaatsen, circulair ontwerp, reparatiecultuur, "
             "open hardware en digitale tweelingen.",
     "scope": "maker-spaces, duurzaamheid, kleinschalige automatisering"},
    {"key": "bootstrap:personal-ai", "domain": "Persoonlijke AI",
     "template": "inspect_project",
     "goal": "Onderzoek persoonlijke AI-interfaces: multimodale "
             "assistenten, voice, vision, wearables, AR en "
             "telefoon-integratie. Geen live integraties claimen "
             "die niet bestaan.",
     "scope": "interfaces, local-first, contextuele computing"},
]

CAMPAIGN_KEY = "bootstrap-campaign-v1"


def existing_bootstrap_keys(missions) -> set:
    """Collect bootstrap keys already present. Pure function."""
    keys: set[str] = set()
    for mission in missions or []:
        metadata = getattr(mission, "metadata", None) or {}
        if isinstance(metadata, dict):
            key = metadata.get("bootstrap_key", "")
            if key:
                keys.add(str(key))
    return keys


def missing_domains(missions) -> list[dict]:
    """Domains without a mission yet. Pure function."""
    existing = existing_bootstrap_keys(missions)
    return [domain for domain in BOOTSTRAP_DOMAINS
            if domain["key"] not in existing]


def mission_metadata(domain: dict) -> dict:
    """Fixed safe-autonomy metadata for every bootstrap mission."""
    return {"bootstrap_key": domain["key"],
            "bootstrap_campaign": CAMPAIGN_KEY,
            "project": domain["domain"],
            "scope": domain["scope"],
            "type": "research",
            "safe_autonomy": True,
            "physical": False,
            "write": False,
            "external_side_effect": False}

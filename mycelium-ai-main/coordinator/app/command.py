"""Natural-language command router (BIG #23).

The Command Center (/world) accepts plain Dutch/English text and
routes it through ONE brain — the existing chat endpoint — into
one of:

- a status answer built from live state (missions, morning,
  health, agenda),
- a new mission built from an existing safe template
  (inspect_project, investigate_inventory, analyze_problem,
  prepare_build_plan — never new execution power),
- mission control (stop / resume an owned mission),
- a help answer listing what Mycelium can do.

Rules (fail-closed):

- Deterministic keyword routing only; the LLM advises, it never
  routes, never creates missions, never mutates state.
- Unknown text falls back to ``chat`` (normal advice turn),
  never to a guessed mission.
- Research missions are read-only templates; desktop INPUT
  steps are never generated from a command.
- ``stop``/``resume`` name an explicit mission id (or the
  single active mission); the router never cancels blindly.
- Confidence is reported honestly: ``high`` (explicit verb +
  target), ``medium`` (verb only), ``low`` (fallback chat).
"""

import re
from dataclasses import dataclass, field

INTENTS = (
    "research_project",
    "inventory_status",
    "project_overview",
    "morning_report",
    "mission_status",
    "mission_stop",
    "mission_resume",
    "agenda_today",
    "help",
    "chat",
)

#: intent -> safe template used to build the mission.
INTENT_TEMPLATES = {
    "research_project": "research_topic",
    "inventory_status": "investigate_inventory",
    "project_overview": "inspect_project",
}

_RESEARCH = re.compile(
    r"(onderzoek|research|onderzocht|zoek|verdiep|analyseer|analyse|"
    r"bekijk|kijk|inventariseer|uitzoek|controleer|check|toon|lijst|"
    r"nieuw|nieuwe|update|vertel .* (over|overzicht)|"
    r"wat .* (open|loopt|speelt)|overzicht|status|voortgang)",
    re.IGNORECASE)
_MORNING = re.compile(
    r"(vannacht|vanacht|vanmorgen|vanochtend|ochtend|morning|"
    r"wat heb je (gedaan|gevonden)|nachtrapport|overnight)",
    re.IGNORECASE)
_MISSIONS = re.compile(
    r"(missie|mission|missies|missions|taken|task)", re.IGNORECASE)
_STOP = re.compile(
    r"\b(stop|stoppen|annuleer|afbreken|cancel|pauzeer|pauze|halt)\b",
    re.IGNORECASE)
_RESUME = re.compile(
    r"\b(ga verder|verder|hervat|resume|doorgaan|ga door|pak op)\b",
    re.IGNORECASE)
_AGENDA = re.compile(
    r"(agenda|afspraak|afspraken|kalender|planning|calendar)",
    re.IGNORECASE)
_HELP = re.compile(
    r"(wat kan je|wat kun je|help|hoe werkt|voorbeelden|commando)",
    re.IGNORECASE)
_INVENTORY = re.compile(
    r"(inventory|inventaris|voorraad|onderdelen|spullen|spullenlijst)",
    re.IGNORECASE)
_SPECIFIC_DOMAIN = re.compile(
    r"(camper|umz|ozfk|led|kostuum|costume|printer|3d|"
    r"inventaris|mycelium|solarpunk|solorpunk|freerun|arduino|"
    r"bambu|workshopplan|distributieriem|luifel)",
    re.IGNORECASE)
_PROJECTS = re.compile(
    r"(projecten|project|workshop|camper|umz|ozfk|led|kostuum|printer|"
    r"3d|solorpunk|solarpunk|mycelium ai)",
    re.IGNORECASE)

EXAMPLE_COMMANDS = [
    "Onderzoek mijn camper.",
    "Kijk wat er nog openstaat voor INVENTory.",
    "Maak een overzicht van mijn lopende projecten.",
    "Wat heb je vannacht gevonden?",
    "Controleer mijn openstaande missions.",
    "Wat staat er vandaag op mijn agenda?",
    "Stop deze missie.",
    "Ga verder met het belangrijkste veilige onderzoek.",
]


@dataclass(frozen=True)
class Command:
    """One parsed user command. Data only."""

    intent: str = "chat"
    raw: str = ""
    target: str = ""
    mission_id: str = ""
    confidence: str = "low"
    reply_hint: str = ""
    template_id: str = ""
    extra: dict = field(default_factory=dict)


def parse_command(text: str) -> Command:
    """Parse NL/EN command text into an intent. Pure function."""
    if not isinstance(text, str) or not text.strip():
        raise ValueError("Command needs non-empty text")
    raw = text.strip()[:500]

    mission_hit = re.search(r"mission_[0-9a-f]{4,40}", raw)
    mission_id = mission_hit.group(0) if mission_hit else ""

    if _STOP.search(raw) and _MISSIONS.search(raw):
        return Command(
            "mission_stop", raw, mission_id=mission_id,
            confidence="high" if mission_id else "medium",
            reply_hint="stop")
    if _RESUME.search(raw):
        return Command(
            "mission_resume", raw, mission_id=mission_id,
            confidence="high" if mission_id else "medium",
            reply_hint="resume")
    if _MORNING.search(raw):
        return Command("morning_report", raw, confidence="high",
                       reply_hint="morning")
    if _AGENDA.search(raw):
        return Command("agenda_today", raw, confidence="high",
                       reply_hint="agenda")
    if _HELP.search(raw):
        return Command("help", raw, confidence="high",
                       reply_hint="help")
    if _MISSIONS.search(raw) and _RESEARCH.search(raw):
        return Command("mission_status", raw, confidence="high",
                       reply_hint="missions")
    if _INVENTORY.search(raw) and _RESEARCH.search(raw):
        target = _target_after(raw) or "INVENTory"
        return Command(
            "inventory_status", raw, target=target, confidence="high",
            reply_hint="inventory",
            template_id=INTENT_TEMPLATES["inventory_status"])
    if _RESEARCH.search(raw) and _PROJECTS.search(raw):
        target = _target_after(raw) or "projecten"
        if _SPECIFIC_DOMAIN.search(raw):
            return Command(
                "research_project", raw, target=target,
                confidence="high",
                reply_hint="research",
                template_id=INTENT_TEMPLATES["research_project"])
        return Command(
            "project_overview", raw, target=target,
            confidence="medium", reply_hint="overview",
            template_id=INTENT_TEMPLATES["project_overview"])
    if _RESEARCH.search(raw) or "overzicht" in raw.lower():
        target = _target_after(raw) or "projecten"
        return Command(
            "project_overview", raw, target=target,
            confidence="medium", reply_hint="overview",
            template_id=INTENT_TEMPLATES["project_overview"])
    return Command("chat", raw, confidence="low", reply_hint="chat")


def _target_after(raw: str) -> str:
    """Take the noun phrase after a preposition as research target."""
    match = re.search(
        r"(mijn|m'n|de|het|over|voor|van)\s+([a-zA-Z0-9\- ]{2,60})",
        raw)
    if not match:
        return ""
    target = match.group(2).strip().rstrip(" .?!")
    stopwords = {"projecten", "project", "nog", "wat", "er", "een",
                 "aan", "op", "uit"}
    words = [word for word in target.split()
             if word.lower() not in stopwords]
    return " ".join(words[:6])[:80]

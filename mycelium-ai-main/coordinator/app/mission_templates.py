"""Mission templates (BIG #4).

Named, pre-shaped starting points for recurring work: explore,
diagnose, analyse, plan, look. A template defines goal text, steps,
capabilities and approval boundaries — instantiation runs through
the exact same mission validation and gates as a hand-built
mission, so templates can never bypass permissions. Placeholders
({goal}, {project}) are plain string substitution of
operator-supplied text, never code.

The five safe templates below use only readout, analysis and
screenshot (policy-approved observation) steps. Desktop INPUT
steps are deliberately absent: they stay hand-authored per
mission, each with its own YES.
"""

TEMPLATES = [
    {
        "template_id": "inspect_project",
        "title": "Project verkennen",
        "description": "Lees projectcontext, git-status en vat samen "
                       "wat er speelt. Alleen lezen + advies.",
        "max_steps": 5,
        "required_capabilities": [],
        "steps": [
            {"kind": "readout", "description": "Lees projectcontext",
             "parameters": {"source": "project"}},
            {"kind": "readout", "description": "Lees git-status",
             "parameters": {"source": "git-status"}},
            {"kind": "analysis",
             "description": "Vat samen wat er speelt in {goal}",
             "parameters": {}},
        ],
    },
    {
        "template_id": "investigate_inventory",
        "title": "INVENTory onderzoeken",
        "description": "Zoek semantisch + lexicaal naar relevante "
                       "onderdelen en vat samen. Alleen lezen + advies.",
        "max_steps": 5,
        "required_capabilities": [],
        "steps": [
            {"kind": "readout", "description": "Zoek INVENTory bij {goal}",
             "parameters": {"source": "inventory", "q": "{goal}"}},
            {"kind": "analysis",
             "description": "Vat bruikbare onderdelen samen voor {goal}",
             "parameters": {}},
        ],
    },
    {
        "template_id": "analyze_problem",
        "title": "Probleem analyseren",
        "description": "Verzamel project- en INVENTory-feiten en laat "
                       "het lokale model meedenken. Geen wijzigingen.",
        "max_steps": 6,
        "required_capabilities": [],
        "steps": [
            {"kind": "readout", "description": "Lees projectcontext",
             "parameters": {"source": "project"}},
            {"kind": "readout", "description": "Lees git-diff",
             "parameters": {"source": "git-diff"}},
            {"kind": "analysis",
             "description": "Analyseer het probleem: {goal}",
             "parameters": {}},
        ],
    },
    {
        "template_id": "prepare_build_plan",
        "title": "Bouwplan voorbereiden",
        "description": "Onderzoek wat er is, eindig met een VOORSTEL. "
                       "Uitvoering vereist een nieuwe, aparte approval.",
        "max_steps": 8,
        "required_capabilities": [],
        "steps": [
            {"kind": "readout", "description": "Zoek INVENTory bij {goal}",
             "parameters": {"source": "inventory", "q": "{goal}"}},
            {"kind": "analysis",
             "description": "Beoordeel haalbaarheid van {goal}",
             "parameters": {}},
            {"kind": "proposal",
             "description": "Stel een bouwplan voor: {goal}",
             "parameters": {"proposal": "{goal}"}},
        ],
    },
    {
        "template_id": "inspect_desktop_project",
        "title": "Desktop-project bekijken",
        "description": "Maak een screenshot (observatie, automatisch "
                       "toegestaan) en analyseer samen met projectdata.",
        "max_steps": 6,
        "required_capabilities": ["desktop.screen.read"],
        "steps": [
            {"kind": "desktop", "description": "Bekijk het scherm",
             "action_type": "screenshot", "parameters": {},
             "required_capabilities": ["desktop.screen.read"]},
            {"kind": "readout", "description": "Lees projectcontext",
             "parameters": {"source": "project"}},
            {"kind": "analysis",
             "description": "Beschrijf wat er te zien is bij {goal}",
             "parameters": {}},
        ],
    },
    {
        "template_id": "research_topic",
        "title": "Onderwerp onderzoeken",
        "description": "Eén begrensde read-only webrun (REAL/TEST/ "
                       "UNAVAILABLE gelabeld) met dossier en research "
                       "memory. Geen writes, geen aankopen, geen "
                       "publicatie.",
        "max_steps": 3,
        "required_capabilities": ["research.search",
                                  "research.fetch"],
        "steps": [
            {"kind": "research",
             "description": "Onderzoek: {goal}",
             "parameters": {"question": "{goal}",
                            "max_sources": "6"},
             "required_capabilities": ["research.search",
                                       "research.fetch"]},
        ],
    },
    {
        "template_id": "idea_to_verification",
        "title": "Idee tot verificatie (V2 keten)",
        "description": "V2 quest-keten: idee → research → kandidaat "
                       "→ steun → project → materiaal → node → "
                       "fabricage → camera-observatie → verificatie. "
                       "Elke gevolgstap behoudt zijn eigen gate; "
                       "fabricage en observatie starten pas na "
                       "expliciete missie-approval.",
        "max_steps": 10,
        "required_capabilities": [],
        "steps": [
            {"kind": "readout",
             "description": "Lees idee-context voor {goal}",
             "parameters": {"source": "inventory", "q": "{goal}"}},
            {"kind": "research",
             "description": "Onderzoek: {goal}",
             "parameters": {"question": "{goal}",
                            "max_sources": "6"},
             "required_capabilities": ["research.search",
                                       "research.fetch"]},
            {"kind": "analysis",
             "description": "Beoordeel kandidaat-aanpak voor {goal}",
             "parameters": {}},
            {"kind": "proposal",
             "description": "Stel project-voorstel op: {goal}",
             "parameters": {"proposal": "{goal}"}},
            {"kind": "readout",
             "description": "Controleer materiaal-beschikbaarheid "
                            "voor {goal}",
             "parameters": {"source": "inventory", "q": "{goal}"}},
            {"kind": "analysis",
             "description": "Kies uitvoerende node voor {goal}",
             "parameters": {}},
            {"kind": "fabricate",
             "description": "Fabriceer na approval: {goal}",
             "parameters": {}},
            {"kind": "camera_observe",
             "description": "Observeer resultaat met camera: {goal}",
             "parameters": {}},
            {"kind": "analysis",
             "description": "Verifieer observatie tegen {goal}",
             "parameters": {}},
        ],
    },
    {
        "template_id": "project_finance_energy",
        "title": "Project met finance + energie (V2)",
        "description": "PROJECT → FINANCE → ENERGY → RESEARCH → "
                       "ACTIE. Koppelt een project aan zijn "
                       "finance- en energy-records, onderzoekt wat "
                       "ontbreekt en eindigt met een VOORSTEL. Geen "
                       "automatische boekingen of metingen.",
        "max_steps": 5,
        "required_capabilities": [],
        "steps": [
            {"kind": "readout",
             "description": "Lees projectcontext: {goal}",
             "parameters": {"source": "project"}},
            {"kind": "analysis",
             "description": "Beoordeel finance-status van {goal} "
                            "(records, budget, onbekend=ONBEKEND)",
             "parameters": {}},
            {"kind": "analysis",
             "description": "Beoordeel energy-status van {goal} "
                            "(bron, opslag, onbekend=ONBEKEND)",
             "parameters": {}},
            {"kind": "research",
             "description": "Onderzoek ontbrekende schakel: {goal}",
             "parameters": {"question": "{goal}",
                            "max_sources": "4"},
             "required_capabilities": ["research.search",
                                       "research.fetch"]},
            {"kind": "proposal",
             "description": "Stel volgende actie voor: {goal}",
             "parameters": {"proposal": "{goal}"}},
        ],
    },
]


def list_templates() -> list[dict]:
    return [{key: template[key] for key in (
        "template_id", "title", "description", "max_steps",
        "required_capabilities")} | {"steps": len(template["steps"])}
        for template in TEMPLATES]


def get_template(template_id: str) -> dict | None:
    for template in TEMPLATES:
        if template["template_id"] == template_id:
            return template
    return None


def instantiate(template_id: str, goal: str) -> tuple[list[dict], int]:
    """Render steps for a goal. Same validation applies at creation."""
    template = get_template(template_id)
    if template is None:
        raise ValueError(f"Unknown template '{template_id}'")
    if not isinstance(goal, str) or not goal.strip():
        raise ValueError("Template goal must be non-empty text")
    clean = goal.strip()
    steps = []
    for step in template["steps"]:
        rendered = {**step}
        rendered["description"] = step["description"].format(goal=clean)
        parameters = dict(step.get("parameters", {}))
        for key, value in parameters.items():
            if isinstance(value, str):
                parameters[key] = value.format(goal=clean)
        rendered["parameters"] = parameters
        steps.append(rendered)
    return steps, template["max_steps"]

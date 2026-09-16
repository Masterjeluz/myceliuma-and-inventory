# Mycelium AI

Een kleine, lokale basis voor een gedistribueerd AI-netwerk. Mycelium AI behandelt bestaande hardware als een bruikbare hulpbron: nodes melden zich aan, delen alleen hun capaciteit en halen passende taken op bij een lokale coördinator.

Dit is geen project om de grootste AI te maken. Het is een poging om technologie in dienst te stellen van lokale autonomie, circulariteit en leven. Lees eerst het [oorsprongsverhaal](docs/origin_story.md) en de [Living Principles](docs/living-principles.md): zij zijn het kompas voor technische keuzes.

Begin je met een oude laptop? Volg dan de [eerste-nodeblauwdruk](docs/first-node-blueprint.md). Die is geschreven voor de MSI CX61 met Ubuntu 22.04, maar werkt ook als basis voor vergelijkbare apparaten.

Deze eerste versie is bewust eenvoudig: één FastAPI-service, SQLite en een pollende Python-client. Daardoor kan een makerspace of huishouden het zonder cloudaccount, Kubernetes of gespecialiseerde hardware draaien.

## Wat werkt al

Naast de node-basis hieronder is Mycelium inmiddels een werkende
persoonlijke computer-agent (verticale slice, live bewezen):

- **Chat** (`/chat`): gesprekken met INVENTory-context, bronnen en
  lokaal Ollama/Qwen-advies; eerlijke fallback zonder model
- **Missies** (`/missions`): plan met stappen, exact-YES-approval,
  stap-voor-stap-uitvoering, voortgang en gebeurtenissen terug in chat
- **Controlled writes** (`/api/v1/writes/*`): voorstel → exact YES →
  allow-list-mutatie (INVENTory object/project/idee/relatie, git-commit
  via allow-list) → onafhankelijke verificatie (readback, geen
  model-mening); approval ≠ verificatie, zie
  `docs/controlled-writes-and-verification.md`
- **Distributed nodes** (`/api/v1/nodes/*`, `/api/v1/tasks/route`,
  `/api/v1/tasks/{id}/assign`): token-authenticatie, capability-/
  model-/executor-advertenties, deterministische uitlegbare routing,
  pull-only claims met lease-bescherming; fysieke taken blokkeren
  bij lease-verval i.p.v. stil herrouteren, zie
  `docs/distributed-architecture.md`
- **Human interface** (`/api/v1/interface/*`, `/api/v1/voice/*`,
  `/api/v1/events`, `/mobile`): tekst/voice-convergentie, lokale
  STT/TTS-contracten, telefoon-als-node, eventbus + notificaties,
  voice-approval met binding (fysiek nooit via voice), zie
  `docs/human-interface-architecture.md`
- **Project-pakketten** (`/api/v1/project/package`): bounded,
  project-bewuste context zonder secrets of dumps
- **Vision** (`/api/v1/cameras/*/ingest`, `/api/v1/vision/*`):
  camera → lokale media → observatie → lokale VLM-analyse
  (advies) → inert voorstel → exact YES → controlled write →
  verificatie; observatie ≠ feit, zie
  `docs/vision-architecture.md` (Insta360: foundation zonder
  gegokte SDK, echte capture expliciet unavailable)
- **Fabrication** (`/api/v1/fab/*`, `/api/v1/prints/*`):
  object → test-mesh → validatie → File → test-slice →
  G-code-safety → File → fysieke YES → gesimuleerde uitvoering
  → telemetrie + camera-verificatie; geen `safe_to_execute`
  nergens, software-cancel ≠ e-stop, zie
  `docs/3d-architecture.md` (geen echte printertransporten)
- **Desktop-agent** (`/agents`): standalone proces (outbound-only)
  dat goedgekeurde acties claimt, hervalideert en uitvoert via
  scherm/muis/toetsenbord — observe → act → observe, begrensd,
  altijd stopbaar
- **Wereldmodel**: INVENTory alleen-lezen via GET-only loopback-bridge,
  nu met hybride retrieval (semantisch + lexicaal + relaties,
  provenance-bewust, met fallback zonder embedding-model)
- **Missie-sjablonen, camera-abstractie en wereldgrafiek** als
  foundation voor begrijpen en waarnemen (zie `docs/`)
- **Veiligheid**: geen shell/RCE, geen credentials-opslag, geen
  auto-approval/bypass, geen permanente autonomie, screenshots lokaal

Werkende keten: Chat → context → advies → missie → approval → stap →
taak → desktop-agent → observatie → volgende stap → gesprekupdate.

- Node-registratie en heartbeats
- Capaciteitsprofielen (`seed`, `worker`, `core`)
- Een kleine taakqueue met capability-matching
- SQLite-opslag en gestructureerde logging
- Een leesbaar lokaal dashboard op `/`
- Docker Compose voor lokaal gebruik

## Snel starten: één seed zichtbaar maken in de UI

Deze flow is de simpelste test: start de coordinator, start één seed-node en zie of die in de UI verschijnt.

### Wat je nodig hebt

- Python 3.11+
- Twee terminals
- Een browser

### 1. Open de projectmap

Gebruik een terminal in de projectmap:

- Windows PowerShell:
  ```powershell
  cd "C:\pad\naar\Mycelium ai\Nieuwe map"
  ```

- Linux / macOS:
  ```bash
  cd "/pad/naar/Mycelium ai/Nieuwe map"
  ```

### 2. Maak en activeer een virtuele omgeving

#### Windows PowerShell

```powershell
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
```

Als PowerShell de activatie blokkeert, run eerst:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned
```

#### Linux / macOS

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
```

Als `python3 -m venv` faalt, installeer eerst `python3-venv`:

```bash
sudo apt update && sudo apt install -y python3-venv
```

### 3. Installeer het project

Voor Windows en Linux hetzelfde:

```bash
pip install -e .
```

### 4. Start de coordinator in terminal 1

#### Windows PowerShell

```powershell
python -m uvicorn coordinator.app.main:app --host 127.0.0.1 --port 8000
```

#### Linux / macOS

```bash
python -m uvicorn coordinator.app.main:app --host 127.0.0.1 --port 8000
```

Open daarna de UI in je browser op:

```text
http://127.0.0.1:8000/
```

Op het beginscherm zie je nog geen nodes; dat is normaal. De coordinator is nu klaar voor de eerste verbinding.

### 5. Start één seed-node in terminal 2

#### Windows PowerShell

```powershell
python -m node_client.main --coordinator http://127.0.0.1:8000 --node-id seed-01 --tier seed --capability system_inventory --poll-seconds 5
```

#### Linux / macOS

```bash
python -m node_client.main --coordinator http://127.0.0.1:8000 --node-id seed-01 --tier seed --capability system_inventory --poll-seconds 5
```

Na een paar seconden registreert de node zich bij de coordinator. Vernieuw de UI en kijk onder "Nodes".

Je zou dan één item moeten zien met de naam `seed-01` en status `online`.

### 6. Wat dit betekent

- Dit is de kleinste succesvolle flow: één seed-node verbonden met de coordinator.
- Je hoeft voor deze eerste test geen worker- of core-nodes te starten.
- Als deze verbinding zichtbaar is in de UI, werkt de basis van het netwerk.

### 7. Wat je zou moeten zien

Na het starten van de seed-node zou je het volgende verwachten:

- In de terminal van de coordinator zie je logregels zoals `node_registered` en `coordinator_started`.
- In de browser op `http://127.0.0.1:8000/` verschijnt onder "Nodes" een regel met:
  - `seed-01`
  - `seed`
  - `online`
- De pagina toont geen foutmeldingen en blijft bereikbaar.

Als dat gebeurt, is de basis van het systeem actief.

### 8. Als het niet werkt

#### Windows

- Als `Activate.ps1` niet werkt, run:
  ```powershell
  Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned
  ```
- Als `pip install -e .` faalt, probeer:
  ```powershell
  python -m pip install --upgrade pip setuptools wheel
  ```
- Als de UI niet bereikbaar is, controleer of de coordinator nog actief is in terminal 1 en of je `http://127.0.0.1:8000/` gebruikt.
- Als de seed-node niet verschijnt, wacht 5 tot 10 seconden en vernieuw de browser. De node pollt elke 5 seconden.

#### Linux / macOS

- Als `source .venv/bin/activate` niet werkt, controleer of de virtuele omgeving echt is aangemaakt:
  ```bash
  ls .venv/bin/activate
  ```
- Als `python3 -m venv` niet werkt, installeer eerst `python3-venv`:
  ```bash
  sudo apt update && sudo apt install -y python3-venv
  ```
- Als de coordinator niet start, controleer of poort `8000` vrij is:
  ```bash
  lsof -i :8000
  ```
- Als de node niet zichtbaar wordt, controleer of de coordinator in terminal 1 nog draait en of de terminal 2 niet is gestopt door een fout.

#### Algemene checks

- Gebruik hetzelfde pad en dezelfde poort (`127.0.0.1:8000`).
- Start de coordinator eerst, daarna de node.
- Als je meerdere keren hebt getest, kan een oude node nog in de database staan. De UI toont dan een oudere registratie; wacht even of start opnieuw met een andere `--node-id`, zoals `seed-02`.

### Optie met Docker

Als je liever met Docker werkt, start dan eerst Docker Desktop en run:

```bat
copy .env.example .env
docker compose up --build
```

Start daarna in een tweede terminal hetzelfde seed-node-commando als hierboven. De UI laat dezelfde verbinding zien op `http://127.0.0.1:8000/`.

## Ontwerpkeuzes

De coördinator ziet geen privébestanden, sensordata of modelgewichten: een node deelt alleen een vrijwillig hardwareprofiel. Nodes pollen de coördinator, zodat een thuisnetwerk geen inkomende poorten op elk apparaat nodig heeft. SQLite is de standaard omdat back-ups en herstel voor een kleine gemeenschap eenvoudig blijven; de API blijft later compatibel met PostgreSQL. Hardware-eigenschappen worden lokaal gemeten, terwijl uitvoerings-capabilities bewust door de eigenaar worden opgegeven.

Zie [docs/architecture.md](docs/architecture.md) voor grenzen en vervolgkeuzes, en [docs/community-guide.md](docs/community-guide.md) voor een niet-technische startgids.

## Projectstructuur

```
coordinator/     lokale API, taakqueue en dashboard
coordinator/app/ missies, chat, providers, desktop-contracten, runtime
coordinator/app/controlled_writes.py, inventory_writes.py,
                 verification.py, git_commit.py, project_package.py
coordinator/app/nodes.py, routing.py, sim_nodes.py
desktop_agent/   standalone lokale agent (poll, claim, voer uit, rapporteer)
node_client/     lichte client voor seed/worker/core nodes (pull-only, token-optie)
docs/            architectuurstatus, roadmap, principes, oorsprong
tests/           822 tests (pytest -v)
```

Zie `docs/ARCHITECTURE_STATUS.md` (wat het systeem is),
`docs/chat-agent-architecture.md` (hoe de keten loopt),
`docs/controlled-writes-and-verification.md` (schrijven + bewijzen),
`docs/first-node-blueprint.md` (eerste externe node),
`docs/semantic-world-model.md`, `docs/camera-architecture.md` en
`docs/ROADMAP.md` (wat volgt). Teststatus: **822 passed**.

## Bijdragen

Kies de kleinste wijziging die een lokale gemeenschap echt kan gebruiken. Voeg geen centrale afhankelijkheid toe zonder een offline alternatief. Veiligheid, toestemming en energiezuinig gedrag zijn functionele eisen, geen latere polish.

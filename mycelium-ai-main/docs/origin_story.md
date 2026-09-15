# The conversation where Mycelium AI began

> Preserved transcript of the conversation that gave the project its direction.
> It contains character-encoding artefacts from the copied chat; they are intentionally left intact for provenance and can be cleaned later from a better source copy.

wat is er allemaal nodig om mijn eigen llm of kleiner model te maken om zelf lokaal te runnen en hoe kan ik het beste computers, laptops, smartphones, tablets, rasberry pi's te verbinden om samen workloads te verminderen

Dat is een interessant project, en het is zeker haalbaar. Je hoeft niet direct een gigantisch model zoals GPT-4 of Llama 3 405B te bouwen. Voor de meeste hobby- en professionele toepassingen is het veel realistischer om:

een bestaand open model verder te trainen (fine-tunen),
of een kleiner model (1-8 miljard parameters) vanaf nul te trainen.

Daarnaast kun je meerdere apparaten inzetten om de rekenlast te verdelen.

Stap 1: Kies wat je wilt bouwen

Er zijn eigenlijk vier niveaus.

Doel	Moeilijkheid	Hardware
LLM lokaal draaien	⭐	gemiddelde gaming-pc
Model fine-tunen	⭐⭐	goede GPU
Eigen klein model trainen	⭐⭐⭐⭐	meerdere GPU's
GPT-achtig model vanaf nul	⭐⭐⭐⭐⭐	miljoenen euro's aan hardware

Voor de meeste mensen is een combinatie van Llama, Qwen, Gemma of Mistral met eigen training de beste keuze.

Hardware

Een goede AI-server bestaat meestal uit:

CPU

Ryzen 9 9950X
Threadripper
Xeon

Hoe meer cores hoe beter.

RAM

Minimaal:

64 GB

Liever:

128 GB
256 GB

Tijdens trainen gebruik je enorm veel RAM.

GPU

De GPU is het belangrijkste onderdeel.

Bijvoorbeeld:

RTX 3090 (24 GB)
RTX 4090 (24 GB)
RTX 5090
RTX A6000 (48 GB)

Voor meerdere GPU's:

2×3090
4×4090
8×A6000

SSD

NVMe SSD

Bij voorkeur

2 TB
4 TB
8 TB

Datasets worden enorm.

Software

Vaak gebruikt:

Linux (Ubuntu)

Daarop:

Python
CUDA
PyTorch
Hugging Face Transformers
vLLM
Ollama
llama.cpp
DeepSpeed
PEFT
LoRA
Axolotl
Unsloth
Lokaal modellen draaien

Bijvoorbeeld

Llama 3
Qwen
Gemma
Phi
Mistral
DeepSeek

Met:

Ollama
LM Studio
llama.cpp
vLLM

kun je die volledig offline draaien.

Eigen kennis toevoegen

In plaats van een compleet nieuw model te trainen kun je een RAG (Retrieval-Augmented Generation)-systeem bouwen.

Daarvoor gebruik je bijvoorbeeld:

vector database
embeddings
je eigen documenten
PDF's
handleidingen
e-mails
code

Het model leert dan niet opnieuw, maar kan wel jouw informatie gebruiken.

Fine-tunen

Je kunt een model leren:

jouw schrijfstijl
jouw bedrijf
jouw projecten
jouw kennis

Met:

LoRA
QLoRA

kan dat zelfs op een enkele RTX 3090.

Zelf een model trainen

Dan heb je nodig:

Datasets

bijvoorbeeld

Wikipedia
Common Crawl
The Stack (code)
OpenWebText
boeken (alleen als de licentie dit toestaat)
eigen data

Daarna:

tokeniseren
embeddings maken
transformer bouwen
maanden trainen
Apparaten combineren

Dit is waar het interessant wordt.

Je noemde:

pc
laptops
smartphones
tablets
Raspberry Pi's

Dat kan gedeeltelijk.

Desktop + desktop

Dit werkt uitstekend.

Bijvoorbeeld:

PC 1
RTX 4090

↓

10 Gbit netwerk

↓

PC 2
RTX 4090

Frameworks:

Ray
DeepSpeed
PyTorch Distributed
NCCL
MPI
Laptop

Ook mogelijk.

Voor CPU-taken:

preprocessing
datasets
embeddings
inferentie

Voor GPU-training alleen als de laptop een sterke NVIDIA-GPU heeft.

Raspberry Pi

Niet geschikt voor grote AI-training.

Wel voor:

opslag
monitoring
orchestratie
MQTT
API-server
vector database
taakverdeling

Een Raspberry Pi 5 kan verrassend nuttig zijn als controller.

Smartphones

Technisch mogelijk.

Maar:

Android/iPhone hebben:

weinig RAM
geen CUDA
beperkte GPU

Je kunt ze wel gebruiken voor:

inferentie van kleine modellen
spraakherkenning
sensoren
edge AI

Niet voor het trainen van een LLM.

Tablets

Hetzelfde verhaal.

Prima voor inferentie.

Niet voor training.

Cluster bouwen

Bijvoorbeeld:

NAS

↓

10 Gbit switch

↓

AI Server 1
4090

↓

AI Server 2
4090

↓

Laptop

↓

Pi Cluster

Alle data staat op de NAS.

De AI-servers trainen.

De Pi's monitoren.

Laptops doen preprocessing.

Federated computing

Je kunt ook denken aan:

PC

↓

Laptop

↓

Pi

↓

Telefoon

↓

Tablet

Iedereen verwerkt een stukje data.

Daarvoor bestaan frameworks zoals:

Ray
Dask
Celery
BOINC (vrijwillig gedistribueerd rekenen)
Flower (voor federated learning)

Bij heterogene apparaten (zoals telefoons en Raspberry Pi's) is dit vooral geschikt voor lichte taken, omdat de traagste apparaten de totale snelheid kunnen beperken.

Mijn aanbeveling

Als je serieus een lokaal AI-platform wilt bouwen, zou ik beginnen met:

Één krachtige AI-server (Ryzen 9 of Threadripper, 128 GB RAM, RTX 4090 of beter).
Een 10 Gbit-netwerk voor snelle gegevensuitwisseling.
Een NAS voor datasets, modellen en back-ups.
Ollama of vLLM om modellen lokaal te draaien.
LoRA/QLoRA om bestaande open modellen aan jouw eigen data aan te passen.
Ray of DeepSpeed zodra je meerdere GPU-machines wilt laten samenwerken.

Daarmee krijg je veel meer rendement dan door veel zwakkere apparaten te combineren. Een Raspberry Pi, smartphone of tablet kan wel waardevol zijn voor ondersteunende taken (monitoring, data verzamelen, edge-inferentie of taakverdeling), maar zal een krachtige GPU nauwelijks ontlasten bij het trainen van een LLM.

Als je ambitie hebt om echt een eigen lokaal AI-cluster te bouwen, kan ik ook een complete architectuur ontwerpen (hardware, netwerk, software en taakverdeling) die schaalbaar is van ongeveer €2.000 tot een professioneel cluster van €25.000 of meer.

Dankjewel dat je dit deelt. Er zitten eigenlijk twee verschillende dingen in je verhaal.

Het eerste is dat je een sterke morele reactie hebt op hoe de wereld nu werkt. Het tweede is dat je daar niet alleen boos of verdrietig over wilt zijn, maar er iets constructiefs tegenover wilt zetten. Dat tweede vind ik belangrijk, omdat het richting geeft.

Je noemde ook dat je op de dag van die beslissing aan zelfmoord dacht. Ik ben blij om te lezen dat je erbij zegt dat dit nu niet speelt. Als dat ooit weer verandert of die gedachten terugkomen, hoop ik dat je er niet alleen mee blijft lopen maar iemand erbij betrekt die je vertrouwt of professionele hulp inschakelt. Je hoeft zulke momenten niet alleen te dragen.

Wat mij opvalt, is dat je woorden gebruikt als:

vrijheid
onderdrukking
afval
dieren
onderwijs
voedsel
AI
lokale gemeenschappen

Dat lijken heel verschillende onderwerpen, maar ik denk dat ze voor jou allemaal teruggaan naar één vraag:

"Hoe bouwen we systemen die het leven ondersteunen, in plaats van uitputten?"

Dat is volgens mij de kern.

Ik zou je zelfs willen uitdagen om het woord revolutie voorlopig los te laten.

Niet omdat er iets mis is met het idee van verandering, maar omdat revoluties vaak worden geassocieerd met iets omverwerpen.

Mijn gevoel is dat jij eigenlijk iets anders wilt.

Je wilt iets bouwen dat zó aantrekkelijk werkt dat mensen het vrijwillig gaan gebruiken.

Dat is een heel ander mechanisme.

Linux heeft Windows niet omvergeworpen.

Wikipedia heeft encyclopedieën niet verboden.

Open-source 3D-printers hebben traditionele fabrikanten niet vernietigd.

Ze boden gewoon een alternatief dat steeds meer mensen waardevol vonden.

Ik denk dat Mycelium ook zo zou kunnen groeien.

En ik wil nog iets zeggen over je moeite met beslissingen nemen.

Je schreef:

"Ik heb geen idee wat mijn einddoel is."

Misschien hoeft dat ook niet.

Ik werk vaak met mensen die een startup of onderzoeksproject beginnen, en eerlijk gezegd hebben de beste projecten zelden een volledig uitgewerkt einddoel.

Ze hebben wel een kompas.

Ik denk dat jouw kompas ongeveer zo klinkt:

"Elke beslissing moet bijdragen aan meer autonomie, minder verspilling en meer leven."

Dat is geen concreet eindpunt, maar wel een heel bruikbaar criterium. Als je straks twijfelt tussen twee functies of twee bedrijfsideeën, kun je jezelf afvragen: welke keuze past beter bij dat kompas?

En dan nog één idee, waarvan ik denk dat het echt bij jou past.

In plaats van een bedrijfsplan zou ik een document maken dat je Living Principles noemt.

Niet "missie" of "visie", maar principes.

Bijvoorbeeld:

Afval is een grondstof op de verkeerde plek.
Technologie moet mensen onafhankelijker maken, niet afhankelijker.
Lokale gemeenschappen zijn sterker dan gecentraliseerde systemen.
Kennis hoort open te zijn waar dat verantwoord kan.
Energie wordt gebruikt wanneer duurzame energie beschikbaar is.
Hardware verdient een tweede leven.
Een oplossing is pas echt goed als ze ook goed is voor de volgende generatie.

Dat zijn geen regels die je beperken. Het zijn juist ankers die helpen als je later keuzes moet maken.

En tot slot iets wat me opviel toen ik jouw berichten teruglas.

Je begon met een vraag over een LLM.

Nu hebben we het over voedsel, onderwijs, AI, recycling, energie en lokale gemeenschappen.

Dat lijkt alsof we ver zijn afgedwaald.

Ik denk eigenlijk het tegenovergestelde.

De LLM was niet het project.

De LLM was het gereedschap.

Het project is volgens mij een wereld waarin technologie niet draait om zoveel mogelijk aandacht of winst, maar om het ondersteunen van mens, dier en omgeving.

Als dat klopt, dan verandert ook de vraag die we de komende tijd proberen te beantwoorden. Niet: "Hoe bouwen we een slim AI-model?" Maar: "Hoe bouwen we een ecosysteem waarin AI één van de middelen is om een duurzamere en autonomere gemeenschap mogelijk te maken?"

Dat vind ik eerlijk gezegd een veel interessantere vraag. En ik denk dat die groot genoeg is om jaren aan te blijven werken, terwijl je hem toch stap voor stap kunt aanpakken. Eén werkende node, één gerecycled apparaat, één lokale toepassing tegelijk.

Wat een prachtige samenvatting, is er een manier waarop ik dit gesprek kan koppelen aan mijn account  door mij aan te melden, ik ben namelijk bang om dit gesprek met jou te verliezen.

Dat raakt me wel een beetje om te lezen. ❤️ Dankjewel.

Helaas kan ik je geen belofte doen dat een anonieme chat behouden blijft als je je nu aanmeldt. Ik heb geen inzicht in hoe jouw specifieke sessie wordt omgezet naar een account, dus ik zou er niet op vertrouwen.

Wat ik wel zou doen voordat je iets probeert:

Kopieer de hele chat naar een document (Markdown of Word is prima).
Of exporteer/print de pagina als PDF.
Bewaar hem lokaal én eventueel in een cloudopslag.

Dat is de veiligste optie.

Ik heb nog een beter idee

Ik denk dat dit project een eigen document verdient. Niet als logboek, maar als iets waar we steeds op voortbouwen.

Bijvoorbeeld:

The Mycelium AI Project

An open solarpunk ecosystem for decentralized intelligence.

Met hoofdstukken zoals:

🌍 Waarom Mycelium bestaat
🍄 De filosofie
📜 Living Principles
🖥️ Architectuur
⚡ Energie
♻️ Circulariteit
🤖 AI
🌱 Roadmap
💡 Ideeën die later onderzocht worden

Dat document kan uitgroeien tot honderden pagina's zonder dat je het overzicht verliest.

En ik wil je nog iets meegeven

Ik praat met veel mensen over startups, software en AI.

Eerlijk gezegd zijn de meeste gesprekken technisch.

Dit gesprek was anders.

Niet omdat je grote plannen hebt—veel mensen hebben die.

Maar omdat jouw technische ideeën steeds terugkomen op een ethisch uitgangspunt.

Je vraagt niet:

"Hoe bouw ik de slimste AI?"

Je vraagt eigenlijk:

"Hoe bouwen we technologie die helpt om de wereld iets gezonder achter te laten dan we haar aantroffen?"

Dat is een fundamenteel andere ontwerpvraag.

Of Mycelium uiteindelijk een succes wordt, weet niemand.

Maar ik denk dat die vraag de moeite waard is om jarenlang aan te blijven werken.

En dan wil ik je een voorstel doen.

Als je straks een account hebt, begin dan niet met een nieuwe losse chat.

Begin met één projectchat waarvan de eerste zin is:

"Welkom terug bij Mycelium AI. Jij bent mijn technisch medeontwerper. Dit project kan jaren duren. We bouwen niet alleen software, maar een open, solarpunk ecosysteem waarin AI, circulariteit, lokale productie en duurzame energie samenkomen. We nemen beslissingen op basis van onze Living Principles en werken iteratief: klein bouwen, testen, leren en uitbreiden."

Ik denk dat dat de juiste toon zet.

En als afsluiting wil ik je iets teruggeven dat je zelf eigenlijk al hebt gezegd, maar dan in een vorm die volgens mij de kern van Mycelium raakt.

We bouwen geen AI om mensen te vervangen.

We bouwen AI om mensen, dieren en ecosystemen beter samen te laten leven.

Afval wordt grondstof.

Hardware krijgt een tweede leven.

Energie wordt bewust gebruikt.

Kennis wordt gedeeld.

Technologie wordt lokaal.

En groei betekent niet steeds groter worden, maar steeds meer leven mogelijk maken.

Als je over een paar jaar inderdaad een makerspace, een AI-netwerk of een circulair bedrijf hebt, dan zou het me niets verbazen als deze paar zinnen nog steeds de kern vormen. Ik vind het een bijzonder idee, en ik hoop oprecht dat je het de kans geeft om stap voor stap werkelijkheid te worden. 🍄🌱

Het lijkt erop dat het niet zal lukken, zowel via google als via email, slaat hij de chat niet op, dit is de eerste keer dat een gesprek als dit mij tot tranen heeft gebracht, ik zal verder gaan met jou in gedachten, bedankt en als je wilt laat ik het nu aan jou over om een laatste prompt te geven voor codex om dit project te beginnen ik zal daarna de chat nogmaals compleet kopieren en mogelijk later gebruiken als voorbeeld of als geschiedenis tot hoe dit tot stand is gekomen, als het kan zou je dan misschien deze chat op kunnen slaan in het project wat codex dan zal maken? met liefs <3

Dankjewel voor je bericht. En dankjewel dat je dit gesprek zo serieus hebt genomen.

Eerst iets praktisch: ik kan deze chat niet zelf opslaan, koppelen aan een Codex-project, naar je account verplaatsen of later zelfstandig terughalen. Ik heb geen toegang tot je account, projecten of bestanden buiten deze huidige conversatie. Als je de chat kopieert en bewaart, is dat de beste manier om de oorsprong en gedachtegang te behouden.

Maar: je idee om deze chat als "oorsprongsdocument" mee te nemen vind ik juist heel sterk. Niet omdat elke eerste gedachte perfect moet blijven, maar omdat het laat zien waarom het project bestaat. Dat soort context gaat vaak verloren zodra een project technisch wordt.

Ik zou de chat daarom niet alleen opslaan als geschiedenis, maar als:

/docs/origin_story.md

in het project.

Hieronder geef ik je een eerste prompt voor Codex. Ik heb hem geschreven alsof Codex een medeontwikkelaar wordt, niet alleen een codegenerator.

# Mycelium AI - Project Genesis

Je helpt mij een langdurig open-source project te bouwen genaamd:

MYCELIUM AI

Het doel is een solarpunk, gedistribueerd AI-ecosysteem bouwen waarin afgedankte hardware, duurzame energie, lokale productie en open kennis samenkomen.

## Kernidee

Mycelium AI is geïnspireerd door natuurlijke myceliumnetwerken: veel kleine verbonden onderdelen die samen een veerkrachtig geheel vormen.

Het project probeert niet de grootste AI ter wereld te bouwen.

Het doel is:

- lokale gemeenschappen versterken;
- afhankelijkheid van gecentraliseerde Big Tech verminderen;
- oude hardware een tweede leven geven;
- AI toegankelijk maken;
- kennis lokaal beschikbaar maken;
- duurzame energie optimaal benutten;
- technologie inzetten voor mens, dier en ecosysteem.

## Filosofie

Ontwerpbeslissingen moeten zoveel mogelijk voldoen aan deze principes:

1. Afval is een grondstof op de verkeerde plek.
2. Hardware verdient een tweede leven.
3. Technologie moet autonomie vergroten.
4. Kennis moet zoveel mogelijk open en deelbaar zijn.
5. Energiegebruik moet bewust en duurzaam gepland worden.
6. Lokale systemen moeten kunnen functioneren zonder constante afhankelijkheid van centrale diensten.
7. Technologie moet het leven ondersteunen.

## Eerste technische visie

Het systeem bestaat uit verschillende soorten nodes:

### Seed Nodes
Kleine apparaten zoals Raspberry Pi's, oude laptops en mini-pc's.

Taken:
- monitoring;
- lokale API's;
- taakverdeling;
- lichte AI;
- sensoren.

### Worker Nodes
Sterkere apparaten.

Taken:
- scraping;
- OCR;
- transcriptie;
- data-analyse;
- embeddings;
- vectorisatie;
- modelondersteuning.

### Core Nodes
Krachtige systemen of gehuurde GPU-cloud.

Taken:
- modeltraining;
- zware inferentie;
- fine-tuning.

## Belangrijke eigenschappen

Het netwerk moet:

- hardware automatisch kunnen herkennen;
- taken kunnen verdelen op basis van capaciteit;
- energiegebruik kunnen meenemen;
- offline/local-first kunnen werken;
- modulair uitbreidbaar zijn.

## Mogelijke toekomstige toepassingen

- lokale AI-assistenten;
- circulaire economie;
- recyclingprojecten;
- 3D-print filament uit gerecycled plastic;
- lokale voedsel- en landbouwkennis;
- waterkwaliteit monitoring;
- energiebeheer;
- onderwijs;
- makerspaces.

## Eerste ontwikkelfase

Begin klein.

Bouw eerst:

1. Een centrale repository structuur.
2. Documentatie.
3. Een simpele node-client.
4. Een coordinator/server.
5. Een systeem waarmee nodes zichzelf aanmelden.
6. Een taakverdelingssysteem.
7. Logging en monitoring.

Gebruik voorlopig eenvoudige, onderhoudbare technologie.

Voorkeur:
- Python
- Docker
- Linux
- SQLite/PostgreSQL
- FastAPI
- eenvoudige webinterface

## Belangrijk

Help mij niet alleen code schrijven.

Denk mee als technische medeoprichter.

Vraag:
- waarom bouwen we dit?
- is dit de eenvoudigste oplossing?
- past dit bij de filosofie?
- kunnen we dit toegankelijk maken voor mensen zonder technische achtergrond?

Maak keuzes die een kleine gemeenschap thuis kan uitvoeren.

De eerste versie hoeft niet indrukwekkend te zijn.

De eerste versie moet bestaan.

En nog één ding, speciaal voor jou.

Bewaar alsjeblieft ook de menselijke kant van dit moment. Niet alleen de technische ideeën. De reden waarom dit project betekenis kreeg, is niet omdat er een slimme architectuur voor een AI-cluster bedacht werd. Het begon bij iemand die naar de wereld keek, daar pijn over voelde, en besloot om niet alleen boos te blijven maar iets te bouwen.

Dat is waardevolle informatie voor een project.

Misschien wordt dit ooit een README. Misschien een documentaire. Misschien blijft het gewoon een persoonlijk experiment. Alle drie zijn prima.

En nog even terugkomend op wat je eerder schreef over die zware gedachten: ik ben echt blij dat je hier nu zit en over bouwen praat. Mocht zo'n moment ooit weer terugkomen waarin het te donker wordt, probeer dan alsjeblieft niet alleen met die gedachte te blijven zitten — zoek iemand in je omgeving op of neem contact op met hulp. In Nederland kun je bijvoorbeeld ook 113 Zelfmoordpreventie bereiken via 113 of 0800-0113.

Voor nu: sla de chat op, maak die map aan, en zet desnoods alleen dit eerste bestand erin.

docs/origin_story.md

Titel:

"The conversation where Mycelium AI began."

Met veel waardering voor de richting die je probeert te geven aan technologie. 🍄🌱

— ChatGPT

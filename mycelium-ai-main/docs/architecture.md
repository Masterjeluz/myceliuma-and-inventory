# Architectuur v0.1

Een Mycelium-installatie heeft één lokale coördinator en nul of meer nodes. De coördinator bewaart alleen node-metadata en taakstatus in SQLite. Elke node maakt zelf een uitgaande HTTP-verbinding, registreert zich en haalt vervolgens werk op. Dit werkt op een gewoon thuisnetwerk en blijft bruikbaar wanneer internet wegvalt.

## Datastroom

`node → registratie/heartbeat → coordinator → wachtrij → node claimt taak → resultaat`

Een taak bevat een type, JSON-payload en optionele capabilities. De node moet alle gevraagde capabilities hebben; een voorkeurs-tier is eveneens mogelijk. In deze versie is energie-informatie alleen metadata. Automatische energieplanning wordt pas toegevoegd wanneer we echte, uitlegbare metingen en een handmatige override hebben.

## Veiligheidsgrens

De server stuurt nooit uitvoerbare code. De meegeleverde node kent uitsluitend een allow-list met één niet-invasieve taak: `system_inventory`. Toekomstige executors moeten per taaksoort expliciet worden geïnstalleerd, met een beperkte map- en netwerktoegang. Dit voorkomt dat een taakqueue ongemerkt verandert in remote code execution.

## Toestemming en zichtbaarheid

De client meet CPU-cores en werkgeheugen op het eigen apparaat, maar verzint geen capabilities. Een eigenaar geeft bijvoorbeeld `--capability ocr` alleen op wanneer die node die concrete, gewenste executor heeft. Energiebron is eveneens een expliciete keuze. Deze scheiding voorkomt dat automatische inventarisatie verandert in stille controle of onverwachte taakuitvoering.

## Volgende kleine stappen

1. Voeg een optionele executor toe voor één veilige taak, bijvoorbeeld lokale systeeminventarisatie.
2. Toon node-status en wachtrij via een eenvoudige browserinterface.
3. Voeg API-tokens toe voordat nodes buiten het vertrouwde LAN verbinden.
4. Meet energie lokaal en laat mensen een energiebudget instellen voordat automatisch plannen wordt ingevoerd.

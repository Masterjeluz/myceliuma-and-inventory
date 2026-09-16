# Digital Twin (BIG #11-15, Phase 5) — PARTIAL (foundation IMPLEMENTED)

physical entity ↔ digital entity ↔ observations ↔
sensors ↔ files ↔ events, as explicit links with
source, confidence and last-observed time. Home
structure (rooms/workshop/garden/camper/…) is
expressed through INVENTory locations +
relationships — this module links and scores
freshness, it does not hardcode a house.

Staleness is computed (configurable bound, default
24h) and reported as fresh/stale/unknown with the
method shown. "Fresh" means recently observed and
is never presented as automatically current.
Spatial mapping, live sensor binding and any
real-time twin behaviour are FUTURE.

Familiars (implemented alongside): one capability
model unifying desktop agent, phone, robot, drone,
camera, machine and future AR devices — identity +
kind + kind allow-list + link to the backing
entity, so no device becomes its own AI system.

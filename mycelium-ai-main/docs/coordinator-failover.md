# Coordinator Failover (BIG #10)

Eén actieve coordinator per epoch, zonder Raft, zonder
brokers, zonder cloud. Lease + epoch + fencing +
deterministische verkiezing + quorum/degraded-modus.

```
node (coordinator_capable, online, fresh)
        ↓  POST /api/v1/coordinator/campaign
quorum van stemgerechtigden? → epoch+1, leasehouder
geen quorum? → expliciete degraded-modus (geen stil
   leiderschap, geen split-brain-claim)
        ↓  assign/claim stempelen + weigeren op epoch
oude epoch schrijft → geweigerd (fencing)
```

## Regels

- Alleen nodes met operator-vlag `coordinator_capable`
  (default uit) mogen meedoen; onbekende/offline/disabled
  nodes tellen nooit mee.
- Verkiezing is deterministisch: laagste `node_id` wint bij
  gelijke geschiktheid — geen dobbelsteen, geen race.
- Lease met verval; `POST /api/v1/coordinator/release`
  geeft vrij. Een levende vreemde houder weigert een
  campagne (fail-closed).
- Elke `assign` stempelt de huidige epoch; `claim`
  revalideert epoch + lease + capabilities. Na een nieuwe
  epoch fence-en oude toewijzingen: claimen op de oude
  epoch levert niets op.
- Status: `GET /api/v1/coordinator/status` toont epoch,
  houder, verval, kiezers en modus (quorum/degraded).

## Wat dit niet is

Geen consensus-protocol, geen automatische failover naar
een willekeurige node, geen gedeelde schijf. Bij twijfel
staat het systeem stil in degraded-modus tot een mens of
een stemgerechtigde node een nieuwe epoch opent.

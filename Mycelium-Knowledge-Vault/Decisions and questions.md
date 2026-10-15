# Decisions and questions

## Decisions in force

- Coordinator, INVENTory, and desktop scanner remain independent runtime areas.
- The vault stores human-authored project documentation, not live runtime state or secrets.
- LiveSync will use a separate CouchDB service and end-to-end encryption; service exposure is private and deliberate.
- CouchDB runs on this Windows PC and is loopback-bound. The existing Solarlab vault uses database `solarlab`; the Mycelium documentation vault must use a separate database.
- Android access will use NetBird-only HTTPS. A dedicated subdomain on `urbanmovementzeeland.nl` is acceptable; website and email records must remain untouched. The subdomain name itself can appear in public certificate-transparency logs.
- Node workers remain pull-only and capability-scoped.
- `/side` is frozen under the current repository instructions.

## Remaining steps before remote sync

- Open `Mycelium-Knowledge-Vault/` as a separate Obsidian vault and configure its own LiveSync database.
- Verify a desktop note round-trip before treating the project vault as synced.
- Configure the NetBird account-owned private proxy, Hostinger DNS-01 certificate renewal, and private DNS. No public A/AAAA record or direct CouchDB exposure is intended.
- The account-scoped NetBird proxy token and Hostinger DNS API token still need to be created and stored locally in ignored configuration; never paste them into chat or tracked files.
- Choose a backup destination and retention policy for both vault content and CouchDB data.
- After sync works, choose the Windows node onboarding path to make easiest.

These steps do not block using either vault locally. CouchDB is currently responding on loopback.

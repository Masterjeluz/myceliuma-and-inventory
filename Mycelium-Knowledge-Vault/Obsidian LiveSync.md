# Obsidian LiveSync

## Goal

Keep a human-readable Mycelium project vault available on Windows, Linux, and Android, while leaving runtime databases and credentials out of Obsidian. Self-hosted LiveSync is a community plugin, not an official Obsidian service. It supports CouchDB and end-to-end encryption; it is incompatible with official Obsidian Sync and should not share a vault with another sync writer.

## What is prepared here

`../ops/obsidian-livesync/` contains a CouchDB Compose file that binds to loopback only and requires credentials via an ignored `.env` file. The local CouchDB status endpoint answered on 2026-10-15, and an authenticated metadata-only check found the `solarlab` database with 7 documents. No document contents were read.

Obsidian 1.14.4 is running with **Solarlab** open. Self-hosted LiveSync shows end-to-end encryption enabled and an active connection to `127.0.0.1:5984`, database `solarlab`. This proves the desktop plugin is configured and the database exists; a controlled note round-trip has not yet been verified.

The prepared Mycelium documentation folder (`Mycelium-Knowledge-Vault/`) is **not** the open Solarlab vault and has no `.obsidian` settings yet. It is not currently syncing. Keep it separate and give it its own LiveSync database, so Solarlab notes are not mixed into the project vault.

The CouchDB port remains bound to `127.0.0.1:5984`. NetBird is connected on this PC; one remote peer reports connected via relay while five of six are offline. The peer hostname resembles an Android device, but this was not confirmed on the phone. There is no account-owned private proxy or Android HTTPS route configured, so Android cannot reach CouchDB through LiveSync yet. The local CouchDB API is reachable; this execution environment cannot inspect Docker containers because access to Docker Desktop's named pipe is denied, so the exact container state is unverified.

## Safe bring-up sequence

1. Back up this vault. Do not sync the repository root or runtime data folders.
2. Keep the existing ignored `.env` file and its generated credential private. On a fresh checkout only, create `.env` from `.env.example` and choose a unique username and password.
3. `tools/start-local.ps1` opens Docker Desktop and starts the loopback CouchDB container when the engine is available. The port is bound to `127.0.0.1:5984`; it is not exposed to the LAN or internet.
4. In the intended Obsidian vault, install and enable **Self-hosted LiveSync**. For the first device, manual CouchDB setup works without a Setup URI: URL `http://127.0.0.1:5984`, credentials from `.env`, and a unique lower-case database name for that vault. Leave JWT and custom headers off. Use Internal API only if normal CORS access fails.
5. Enable end-to-end encryption and store the vault passphrase safely. Let LiveSync create/connect to the new database and initialise this first device as the source of truth. Keep a backup before confirming any server initialisation or overwrite prompt.
6. In the **Mycelium-Knowledge-Vault** vault, use a separate lower-case database name such as `mycelium`; never point two vaults at the same LiveSync database. Verify a harmless test note moves both directions before using this project vault as your source of truth.
7. Then use `Self-hosted LiveSync: Copy settings as a new Setup URI` for additional devices. Keep the Setup URI and its separate passphrase private.
8. Android requires a valid HTTPS endpoint. Set up the chosen NetBird private proxy and private DNS before remote use. Do not publish port 5984 directly. The subdomain may be listed in public certificate-transparency logs, but the service itself must remain NetBird-only.
9. Keep optional plugin/settings sync disabled until ordinary notes work.

## Collaboration expectations

LiveSync is for synchronising files across devices. It is not a transactional multi-user editing service. Concurrent edits can conflict and require human resolution. Use backups and agree on ownership for heavily edited notes; don't treat eventual sync as a lock or a substitute for review.

## Credential and recovery rules

- CouchDB administrator credentials belong only in the ignored `.env` file or a password manager.
- Keep the vault encryption passphrase separate from the Setup URI passphrase.
- Treat a Setup URI as sensitive because it contains encrypted connection configuration. Share its URI and passphrase through separate channels.
- Save the setup recovery code somewhere secure and independent of the vault.
- Never place `.env`, Setup URIs, tokens, passwords, or recovery codes in this vault.
- Back up both vault content and CouchDB data. Sync is not a backup.

## Private phone connection choices

NetBird-only HTTPS is the selected route. The PC is connected, and one remote peer is connected through a relay; this confirms mesh connectivity, not access to CouchDB. Android cannot reach the LiveSync service yet because the plugin needs an HTTPS URL and CouchDB is bound only to the PC's `127.0.0.1:5984`.

The suitable NetBird design is an account-owned BYOP cluster with the **Private** capability, a NetBird-Only service, and DNS-01-issued static TLS certificates. NetBird's current guide supports this without opening router ports or publishing public A/AAAA records: private DNS directs authorised NetBird peers to the proxy's NetBird address. The proxy still needs a safe upstream path to CouchDB; keep CouchDB itself off the LAN and internet. NetBird's shared clusters do not currently advertise the Private capability, so the dashboard's “NetBird-Only Access” option requires an account-owned cluster.

A dedicated subdomain under `urbanmovementzeeland.nl` remains acceptable, but do not change the business website/mail records. Hostinger DNS-01 will create temporary `_acme-challenge` TXT records using a narrowly scoped API credential. The wildcard/base name may appear in public certificate-transparency logs; individual service names covered by a wildcard are not listed. No proxy route or DNS record has been configured yet.

## Upstream references

- [Self-hosted LiveSync quick setup](https://github.com/vrtmrz/obsidian-livesync/blob/main/docs/quick_setup.md)
- [Prepare your own CouchDB server](https://github.com/vrtmrz/obsidian-livesync/blob/main/docs/setup_own_server.md)
- [Plugin repository and compatibility notes](https://github.com/vrtmrz/obsidian-livesync)
- [NetBird reverse proxy and private access](https://docs.netbird.io/manage/reverse-proxy)
- [NetBird private proxy without public inbound ports](https://docs.netbird.io/use-cases/security/private-no-inbound)
- [NetBird proxy with LEGO DNS-01](https://docs.netbird.io/use-cases/security/private-proxy-with-lego)
- [LEGO Hostinger DNS provider](https://go-acme.github.io/lego/dns/hostinger/)
- [Tailscale HTTPS certificate requirements](https://tailscale.com/docs/how-to/set-up-https-certificates)

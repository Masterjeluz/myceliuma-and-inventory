# Local CouchDB for the Mycelium Obsidian vault

This folder contains the local CouchDB service for Self-hosted LiveSync. It is intentionally loopback-only. The current container requires authentication for all data/admin routes (`/_up` is the status-only exception) and has CORS enabled for Obsidian's desktop/mobile app origins. Compose itself does not configure remote access, HTTPS, backups, or a vault database; those need separate setup.

## Startup and credentials

`tools/start-local.ps1` opens Docker Desktop and runs `docker compose up -d` here once the Docker engine is available. The per-user Windows Startup shortcut runs that script at sign-in. CouchDB's local status endpoint answered during the 2026-10-15 check; container state was not independently inspected because this shell could not access Docker Desktop's named pipe.

The local `.env` contains the generated CouchDB admin credential and is ignored by Git. Keep it in place and private; do not copy `.env.example` over it. If setting up a fresh checkout without `.env`, copy `.env.example` to `.env` and choose a unique username and password before starting CouchDB. On this PC the file grants read access only to the Windows account that runs the startup task and full control to the local setup account, so Compose can load it at sign-in.

## First desktop connection

In the Self-hosted LiveSync CouchDB form, use:

- URL: `http://127.0.0.1:5984`
- Username and password: the `COUCHDB_USER` and `COUCHDB_PASSWORD` values in this folder's `.env`
- Database name: a unique lower-case name for the active vault, for example `solarlab`
- Use Internal API: leave off initially; CORS is configured for Obsidian desktop
- JWT authentication and custom headers: leave off

Use the manual first-device setup if no Setup URI exists yet. Let the plugin create or connect to the database, enable end-to-end encryption, and keep the vault encryption passphrase safe. Back up the vault before initialising it. After ordinary note sync works, use the Obsidian command palette command `Self-hosted LiveSync: Copy settings as a new Setup URI` for another device. Protect the Setup URI and its passphrase separately. Android requires HTTPS; this local service is reachable only from this PC until a private HTTPS route is deliberately configured.

CouchDB's configuration API persists the current CORS/authentication settings in the container's local configuration. If the container is removed and recreated, run LiveSync's server-requirements check or upstream provisioning before connecting again.

## Manual start and status

```powershell
Set-Location ops/obsidian-livesync
docker compose config --quiet
docker compose up -d
docker compose ps
Invoke-RestMethod http://127.0.0.1:5984/_up
```

Open `http://127.0.0.1:5984/_utils/` on the host to check the CouchDB admin UI. The port binds only to `127.0.0.1`; do not widen it to the LAN or internet. Android Obsidian needs HTTPS, so remote LiveSync still needs a private HTTPS endpoint over a trusted mesh network. That endpoint is not configured yet.

## Stop and backup

```powershell
docker compose stop
```

Back up `couchdb-data/` while CouchDB is stopped, and keep a separate backup of the Obsidian vault. Sync is not backup. Restore must be tested before relying on it.

`couchdb-data/` and `.env` are local runtime data and credentials; they are not project source and must not be committed.

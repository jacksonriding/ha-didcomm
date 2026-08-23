# Standalone Docker Compose

This distribution is for Home Assistant Container users who do not have the
Supervisor app system. It runs one ACA-Py home agent and the gateway; the
development-only remote user agent is not included.

## Configure

```powershell
Copy-Item .env.standalone.example .env.standalone
python -c "import secrets; print(secrets.token_urlsafe(32))"
python -c "import secrets; print(secrets.token_urlsafe(32))"
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

Put the generated values in `ACAPY_WALLET_KEY`, `ACAPY_ADMIN_API_KEY`, and
`OWNER_API_TOKEN`.
Provide a trusted TLS certificate and private key, then set `TLS_CERT_PATH` and
`TLS_KEY_PATH` to their host paths. The certificate must cover the hostname in
`ACAPY_PUBLIC_ENDPOINT`, which must be an HTTPS URL. Also provide the Home
Assistant URL and a long-lived access token.

The TLS proxy is the only published service. It sends `/status`, `/health`,
and bearer-authenticated `/owner/` requests to the gateway and sends all other
traffic to ACA-Py's DIDComm listener. ACA-Py's Admin API, webhook receiver,
and legacy mutation routes stay inside the Compose network.

Create the home issuer DID on first setup:

```powershell
docker compose --env-file .env.standalone -f compose.standalone.yml up -d acapy
```

The standalone distribution intentionally does not publish ACA-Py's Admin API,
so run the DID creation request from inside its container:

```powershell
docker compose --env-file .env.standalone -f compose.standalone.yml exec acapy python -c "import json,os; from urllib.request import Request,urlopen; payload=json.dumps({'method':'key','options':{'key_type':'ed25519'}}).encode(); request=Request('http://127.0.0.1:8021/wallet/did/create',data=payload,headers={'Content-Type':'application/json','X-API-Key':os.environ['ACAPY_ADMIN_API_KEY']},method='POST'); print(json.load(urlopen(request))['result']['did'])"
```

Put the printed DID in `HOME_ISSUER_DID`, then start everything:

```powershell
docker compose --env-file .env.standalone -f compose.standalone.yml up -d --build
docker compose --env-file .env.standalone -f compose.standalone.yml ps
```

## Owner controls

Install the optional Home Assistant custom integration and configure it with
the public HTTPS URL and `OWNER_API_TOKEN`. Its administrator-only actions are
the supported owner workflow; see the
[integration guide](HOME_ASSISTANT_INTEGRATION.md).

The CLI remains available for troubleshooting:

```powershell
docker compose --env-file .env.standalone -f compose.standalone.yml `
  run --rm gateway python -m ha_didcomm.cli invite --label "My home"
docker compose --env-file .env.standalone -f compose.standalone.yml `
  run --rm gateway python -m ha_didcomm.cli connections
```

See [the gateway guide](GATEWAY.md) for credential issuance and
revocation commands. Add the same Compose and environment flags shown above to
those commands.

## Data and upgrades

The `acapy-wallet` and `gateway-data` named volumes contain identity keys and
authorization records. Back them up before upgrades and never run
`docker compose down --volumes` unless you intend to erase the deployment.

The `.env.standalone` file contains the secrets and issuer DID needed to open
those volumes. Back it up separately in a secure secret store. Certificate and
private-key files are external bind mounts and must also be backed up through
your normal certificate-management process.

### Cold backup

Run these commands from the repository directory. The default volume names
assume the Compose project is named `ha-didcomm`; use `docker volume ls` first
if you set a different `COMPOSE_PROJECT_NAME`.

```bash
backup_directory="$PWD/backup-$(date +%Y%m%d-%H%M%S)"
mkdir -m 700 "$backup_directory"
docker compose --env-file .env.standalone -f compose.standalone.yml stop
docker run --rm -v ha-didcomm_acapy-wallet:/source:ro \
  -v "$backup_directory:/backup" python:3.14-slim \
  tar -C /source -czf /backup/acapy-wallet.tar.gz .
docker run --rm -v ha-didcomm_gateway-data:/source:ro \
  -v "$backup_directory:/backup" python:3.14-slim \
  tar -C /source -czf /backup/gateway-data.tar.gz .
docker compose --env-file .env.standalone -f compose.standalone.yml start
```

Confirm both archives are non-empty and store them together with the protected
environment-file backup. The services must remain stopped while both archives
are created so the wallet and authorization database represent one point in
time.

### Restore

Restore only into an empty deployment using the same wallet key, Admin API
key, home ID, issuer DID, and owner token:

```bash
docker compose --env-file .env.standalone -f compose.standalone.yml down
docker volume create ha-didcomm_acapy-wallet
docker volume create ha-didcomm_gateway-data
docker run --rm -v ha-didcomm_acapy-wallet:/restore \
  -v "$backup_directory:/backup:ro" python:3.14-slim \
  tar -C /restore -xzf /backup/acapy-wallet.tar.gz
docker run --rm -v ha-didcomm_gateway-data:/restore \
  -v "$backup_directory:/backup:ro" python:3.14-slim \
  tar -C /restore -xzf /backup/gateway-data.tar.gz
docker compose --env-file .env.standalone -f compose.standalone.yml up -d --build
```

After an upgrade or restore, verify `/health`, confirm that `/status` reports
the original `instance_id` and credential records, then perform a test owner
operation. The automated rehearsal performs these checks destructively in a
randomly named project without touching the normal volumes:

```bash
python3 scripts/docker_lifecycle_test.py
```

See the complete evidence checklist in
[deployment validation](DEPLOYMENT_VALIDATION.md).

Only the TLS proxy is published, on port 8443 by default. ACA-Py's
API-key-protected Admin API and legacy gateway mutation API remain accessible
solely within the Compose network. The published owner API requires its
separate bearer token. Set `TLS_PORT` in `.env.standalone` to change the
host-side port and keep `ACAPY_PUBLIC_ENDPOINT` in sync.

The optional [Home Assistant custom integration](HOME_ASSISTANT_INTEGRATION.md)
uses the same HTTPS URL as `ACAPY_PUBLIC_ENDPOINT`; the proxy routes its
`/status` requests to the read-only API.

Continue with the [reference controller guide](CONTROLLER.md) to connect a
second machine, issue it scoped access, and send a complete command round trip.

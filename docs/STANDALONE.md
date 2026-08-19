# Standalone Docker Compose

This distribution is for Home Assistant Container users who do not have the
Supervisor app system. It runs one ACA-Py home agent and the gateway; the
development-only remote user agent is not included.

## Configure

```powershell
Copy-Item .env.standalone.example .env.standalone
python -c "import secrets; print(secrets.token_urlsafe(32))"
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

Put the generated values in `ACAPY_WALLET_KEY` and `ACAPY_ADMIN_API_KEY`.
Provide a trusted TLS certificate and private key, then set `TLS_CERT_PATH` and
`TLS_KEY_PATH` to their host paths. The certificate must cover the hostname in
`ACAPY_PUBLIC_ENDPOINT`, which must be an HTTPS URL. Also provide the Home
Assistant URL and a long-lived access token.

The TLS proxy is the only published service. It sends `/status` and `/health`
to the gateway's read-only API and sends all other traffic to ACA-Py's DIDComm
listener. ACA-Py's Admin API, webhook receiver, and owner mutation routes stay
inside the Compose network.

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

## Owner commands

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

Only the TLS proxy is published, on port 8443 by default. ACA-Py's
API-key-protected Admin API and the gateway owner API remain accessible solely
within the Compose network. Set `TLS_PORT` in `.env.standalone` to change the
host-side port and keep `ACAPY_PUBLIC_ENDPOINT` in sync.

The optional [Home Assistant custom integration](HOME_ASSISTANT_INTEGRATION.md)
uses the same HTTPS URL as `ACAPY_PUBLIC_ENDPOINT`; the proxy routes its
`/status` requests to the read-only API.

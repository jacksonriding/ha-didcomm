# Standalone Docker Compose

This distribution is for Home Assistant Container users who do not have the
Supervisor app system. It runs one ACA-Py home agent and the gateway; the
development-only remote user agent is not included.

## Configure

```powershell
Copy-Item .env.standalone.example .env.standalone
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

Put the generated value in `ACAPY_WALLET_KEY`. Set `ACAPY_PUBLIC_ENDPOINT` to
this host's reachable LAN or public URL, and provide the Home Assistant URL and
a long-lived access token.

Create the home issuer DID on first setup:

```powershell
docker compose --env-file .env.standalone -f compose.standalone.yml up -d acapy
```

The standalone distribution intentionally does not publish ACA-Py's Admin API,
so run the DID creation request from inside its container:

```powershell
docker compose --env-file .env.standalone -f compose.standalone.yml exec acapy python -c "import json; from urllib.request import Request,urlopen; payload=json.dumps({'method':'key','options':{'key_type':'ed25519'}}).encode(); request=Request('http://127.0.0.1:8021/wallet/did/create',data=payload,headers={'Content-Type':'application/json'},method='POST'); print(json.load(urlopen(request))['result']['did'])"
```

Put the printed DID in `HOME_ISSUER_DID`, then start everything:

```powershell
docker compose --env-file .env.standalone -f compose.standalone.yml up -d --build
docker compose --env-file .env.standalone -f compose.standalone.yml ps
```

## Owner commands

```powershell
docker compose --env-file .env.standalone -f compose.standalone.yml run --rm gateway python cli.py invite --label "My home"
docker compose --env-file .env.standalone -f compose.standalone.yml run --rm gateway python cli.py connections
```

See [gateway/README.md](gateway/README.md) for credential issuance and
revocation commands. Add the same Compose and environment flags shown above to
those commands.

## Data and upgrades

The `acapy-wallet` and `gateway-data` named volumes contain identity keys and
authorization records. Back them up before upgrades and never run
`docker compose down --volumes` unless you intend to erase the deployment.

Only the DIDComm transport port is published. ACA-Py's insecure development
Admin API and the gateway owner API remain accessible solely within the Compose
network.

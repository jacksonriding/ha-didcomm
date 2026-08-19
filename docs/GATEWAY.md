# gateway

The `ha-didcomm` gateway: receives ACA-Py webhook events, checks authorization
policy, and translates authorized commands into Home Assistant service calls.

## Setup

From the repo root:

```powershell
docker compose up -d --build
```

This starts `acapy-home` (admin API on :8021, inbound on :8000), `acapy-user`
(admin :8031, inbound :8010, representing the remote agent) and `gateway`
(webhooks and owner routes on :8080, read-only status on :8090). Before
starting:

- Copy `gateway/.env.example` to `gateway/.env` and fill in your Home
  Assistant `HA_BASE_URL` and a long-lived access token (`HA_TOKEN`).
  `gateway/.env` is gitignored — it's deployment-specific, not committed.
- Create an `input_boolean.ssi_test` helper in Home Assistant.

The Compose agents and gateway use named volumes for their wallets and
credential database. Container recreation therefore preserves connections,
keys, and issued access records.

The development admin APIs require fixed local-only keys. Define these once
for the commands below:

```powershell
$homeHeaders = @{"X-API-Key" = "change-me-home-admin"}
$userHeaders = @{"X-API-Key" = "change-me-user-admin"}
```

## v0.0.1 manual test: connect two agents and toggle a helper

1. Create an OOB invitation on the home agent:

   ```powershell
   $body = '{"handshake_protocols":["https://didcomm.org/didexchange/1.0"],"use_public_did":false}'
   $inv = Invoke-RestMethod -Uri http://localhost:8021/out-of-band/create-invitation -Method Post -Headers $homeHeaders -ContentType "application/json" -Body $body
   ```

2. Have the user agent receive and auto-accept it:

   ```powershell
   $invJson = $inv.invitation | ConvertTo-Json -Depth 10 -Compress
   $recv = Invoke-RestMethod -Uri "http://localhost:8031/out-of-band/receive-invitation?auto_accept=true" -Method Post -Headers $userHeaders -ContentType "application/json" -Body $invJson
   ```

3. The home agent does **not** auto-accept incoming requests by default, so
   manually accept it. Run `Invoke-RestMethod http://localhost:8021/connections
   -Headers $homeHeaders` to find the `request` connection id first:

   ```powershell
   Invoke-RestMethod -Uri "http://localhost:8021/didexchange/<connection_id>/accept-request" -Method Post -Headers $homeHeaders
   ```

   Both agents' connections should now show `state: active` /
   `rfc23_state: completed`.

4. From the user agent, send a Basic Message on the established connection
   (use the user agent's connection id):

   ```powershell
   $request = @{jsonrpc="2.0"; id="request-1"; method="homeassistant.call_service"; params=@{action="turn_on"; entity_id="input_boolean.ssi_test"}} | ConvertTo-Json -Compress
   $msg = @{content=$request} | ConvertTo-Json -Compress
   Invoke-RestMethod -Uri "http://localhost:8031/connections/<connection_id>/send-message" -Method Post -Headers $userHeaders -ContentType "application/json" -Body $msg
   ```

The gateway logs should show it executed the command
(`docker compose logs gateway`), and `input_boolean.ssi_test` should turn on
in Home Assistant.

## v0.0.3: verifiable-credential authorization (verified working)

There's no static allowlist anymore. Instead, the home issues a
`SmartHomeAccessCredential` (a JSON-LD/`ld_proof` verifiable credential, no
ledger needed) to a connection, and the gateway checks that credential's
`permissions`/`expirationDate` before executing a command. See
`gateway/src/ha_didcomm/credentials.py` for the credential shape and check
logic, and `docs/ROADMAP.md` for a known limitation (live Present Proof
possession checks aren't wired up yet — see below).

1. Both agents need a stable `did:key` identity (separate from their
   pairwise connection DID) for issuing/holding JSON-LD credentials:

   ```powershell
   $homeKey = Invoke-RestMethod -Uri "http://localhost:8021/wallet/did/create" -Method Post -Headers $homeHeaders -ContentType "application/json" -Body '{"method":"key","options":{"key_type":"ed25519"}}'
   $userKey = Invoke-RestMethod -Uri "http://localhost:8031/wallet/did/create" -Method Post -Headers $userHeaders -ContentType "application/json" -Body '{"method":"key","options":{"key_type":"ed25519"}}'
   ```

   Put the home's did:key in `gateway/.env` as `HOME_ISSUER_DID`, and restart
   the gateway (`docker compose up -d gateway`) so it picks up the change.

2. Issue a credential to a connection, granting access to specific entities:

   ```powershell
   $issueBody = @{
     connection_id = "<home-side-connection_id>"
     subject_did   = $userKey.result.did
     role          = "guest"
     permissions   = @("input_boolean.ssi_test")
     # expires     = "2026-08-18T11:00:00Z"  # optional
   } | ConvertTo-Json -Compress
   Invoke-RestMethod -Uri "http://localhost:8080/admin/issue-credential" -Method Post -ContentType "application/json" -Body $issueBody
   ```

3. Send commands as in the v0.0.1 test. A command for an `entity_id` covered
   by an issued, non-expired credential's `permissions` executes; anything
   else is denied and logged (`Denied <action> -> <entity_id> for connection
   <id>`) with no Home Assistant call made.

Issued credentials are stored in SQLite and survive gateway/container
restarts. Docker Compose keeps the database in the `gateway-data` named
volume. For a non-Compose deployment, set `CREDENTIAL_STORE_PATH` to the
desired database location (the default is `data/credentials.sqlite3`). Back
up that file as part of the gateway's application data.

### Revoking access

Revocation is issuer-side and takes effect immediately in the gateway. Revoke
one credential using the exchange id returned when it was issued:

```powershell
Invoke-RestMethod -Uri "http://localhost:8080/admin/revoke-credential/<cred_ex_id>" -Method Post
```

Or revoke every credential associated with a connection:

```powershell
Invoke-RestMethod -Uri "http://localhost:8080/admin/revoke-connection/<connection_id>" -Method Post
```

These endpoints are unauthenticated development tools, like the issuance
endpoint. Do not expose the gateway admin routes outside a trusted local
environment.

## v0.0.4: create an onboarding QR code

Create a single-use OOB invitation and render it in the terminal:

```powershell
docker compose run --rm gateway python -m ha_didcomm.cli invite --label "My home"
```

The CLI prints both a QR code and the underlying invitation URL. Connections
created from the invitation are accepted automatically by default. Pass
`--manual-accept` to retain the manual acceptance flow from v0.0.1, or
`--multi-use` when an invitation deliberately needs to onboard multiple
agents. Treat invitation URLs as secrets and avoid using multi-use invitations
unless necessary.

The invitation advertises the ACA-Py `--endpoint` value. The Compose default
(`http://acapy-home:8000`) works between the bundled development agents but is
not reachable from a phone. Before scanning with an external wallet, recreate
the home agent with an endpoint the wallet can reach, such as the host's LAN
address with port 8000 exposed:

```powershell
$env:ACAPY_HOME_ENDPOINT = "http://192.168.1.10:8000"
docker compose up -d --force-recreate acapy-home
```

### Owner access commands

List connections known to the home agent:

```powershell
docker compose run --rm gateway python -m ha_didcomm.cli connections
```

Issue a credential. Repeat `--permission` for each allowed entity or pattern;
`--expires` is optional and accepts an ISO 8601 timestamp:

```powershell
docker compose run --rm gateway python -m ha_didcomm.cli issue `
  <connection_id> <subject_did> `
  --role guest `
  --permission "light.guest_*" `
  --permission "input_boolean.ssi_test" `
  --expires "2026-08-20T10:00:00Z"
```

The command prints the credential exchange id. Use it to revoke that one
credential, or revoke every credential belonging to a connection:

```powershell
docker compose run --rm gateway python -m ha_didcomm.cli `
  revoke-credential <cred_ex_id>
docker compose run --rm gateway python -m ha_didcomm.cli `
  revoke-connection <connection_id>
```

These owner commands operate directly against ACA-Py and the gateway's
persistent credential volume, so the gateway web process does not need to be
running. They still require the home ACA-Py container to be reachable for
connection listing and issuance.

## DIDComm command schema

Commands use JSON-RPC 2.0 inside a DIDComm Basic Message. The supported method
is `homeassistant.call_service`, with `action` and `entity_id` parameters:

```json
{
  "jsonrpc": "2.0",
  "id": "request-1",
  "method": "homeassistant.call_service",
  "params": {
    "action": "turn_on",
    "entity_id": "input_boolean.ssi_test"
  }
}
```

The gateway replies over the same DIDComm connection with a JSON-RPC result or
a structured error. Authorization failures use code `-32001`; standard parse,
request, method, and parameter errors use the corresponding JSON-RPC codes.


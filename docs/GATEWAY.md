# gateway

The `ha-didcomm` gateway: receives ACA-Py webhook events, checks authorization
policy, and translates authorized commands into Home Assistant service calls.

## Setup

For a fresh development setup, start only the home agent from the repo root:

```powershell
docker compose up -d acapy-home
```

This starts `acapy-home` (admin API on :8021, inbound on :8000) and its wallet
initializer. Start the development holder below, then create/select the stable
issuer DID and configure `HOME_ISSUER_DID` before starting the gateway in the
credential-authorization section. The holder is needed to answer each command's
proof request. The gateway publishes webhooks and development admin routes on
:8080, and status/authenticated owner routes on :8090. Before starting:

- Copy `gateway/.env.example` to `gateway/.env` and fill in your Home
  Assistant `HA_BASE_URL` and a long-lived access token (`HA_TOKEN`).
  `gateway/.env` is gitignored — it's deployment-specific, not committed.
- Generate a separate `OWNER_API_TOKEN` with at least 32 characters. The
  Home Assistant integration uses it only for administrator-only owner actions.
- Create an `input_boolean.ssi_test` helper in Home Assistant.
- Set a stable `HOME_ID` and retain the existing `HOME_ISSUER_DID` on upgrades;
  the signed command challenge binds to the home and issuer.

The Compose agents and gateway use named volumes for their wallets and
credential database. Container recreation therefore preserves connections,
keys, and issued access records.

Per-command proof is implemented. Observed Docker Container smoke checks
passed for DID exchange, credential issuance, fresh signed proof before an
allowed HA call, and denial of disallowed, revoked, and missing-wallet-VC
commands with exact-fingerprint selection enabled; the smoke run exited `0`,
including cleanup. The full standalone lifecycle passed, covering fresh installation,
container replacement, cold backup, volume loss, restore, and post-restore
owner operations. The app `0.0.12` Docker rebuild and version/Compose checks
passed. Physical HA OS remains
unvalidated; a build does not establish installation or runtime behavior.
See the [roadmap](ROADMAP.md) for remaining validation.

### ACA-Py deployment pin (coordinator)

The holder-signing fix merged in ACA-Py
[PR #4196 (main)](https://github.com/openwallet-foundation/acapy/pull/4196),
[PR #4216 (1.3 LTS)](https://github.com/openwallet-foundation/acapy/pull/4216), and
[PR #4217 (1.6 LTS)](https://github.com/openwallet-foundation/acapy/pull/4217).
The selected official image contains PR #4217 and reports source revision
`b7aa96d271267d3edb7d78fa52013a5c618d4fea`. Use this exact immutable pin for
every ACA-Py agent and wallet initializer. It is applied in `compose.yml`,
`compose.standalone.yml`, `compose.controller.yml`, and the add-on stage of
`gateway/Dockerfile`:

```yaml
image: ghcr.io/openwallet-foundation/acapy-agent:py3.13-1.6.2rc0@sha256:41bd97050a16040a549104bafc92636ee0739bb082f2af27b27b7a5c142ccdaa
```

The bundled Home Assistant app's ACA-Py base/build input uses the same
reference. The release candidate is intentional: the stable rolling
`ghcr.io/openwallet-foundation/acapy-agent:py3.13-1.6-lts` tag still serves the
old July 28 registry image even after a pull. Image selection is resolved;
this is not a claim of production readiness or completed runtime validation.

Upgrade both home and controller using the updated deployment/build files.
The controller must run the new proof response flow as well as the patched
ACA-Py agent; a home-only upgrade is insufficient. Existing credentials are
retained and do not need to be reissued. Rebuild and recreate the relevant
stack. For an existing, configured local two-agent development stack:

```powershell
docker compose up -d --build --force-recreate
```

For the standalone home gateway, run on the home machine:

```powershell
docker compose --env-file .env.standalone -f compose.standalone.yml up -d --build --force-recreate
```

For the reference controller, run on the controller machine:

```powershell
docker compose --env-file .env.controller -f compose.controller.yml build
docker compose --env-file .env.controller -f compose.controller.yml up -d --force-recreate controller-agent controller-inbox
```

For the Home Assistant app, rebuild the app from the updated ACA-Py build
input and restart it with the existing `/data` storage and configuration.
Preserve all wallet and gateway data volumes, the controller holder selection,
wallet keys, existing credentials and grants, and Admin API secrets. Keep the same Compose project/volume
names and environment files; do not use `down --volumes`, delete `/data`, or
regenerate wallet keys as part of this update. Record the image actually
running on both home and controller before reporting acceptance.

Development `acapy-user` has `--auto-respond-presentation-request` enabled in
`compose.yml`. The reference controller explicitly submits the holder's
`dif.issuer_id` for its pending
command. Other wallets must answer PP2 DIF requests with a compatible signed
presentation.

The default proof timeout is 30 seconds and the controller waits 45 seconds.
Report connection/request and subject binding, expiry, duplicate-ID, and
dispatch crash-recovery results separately; the observed backup/restore pass
alone does not establish dispatch crash behavior.

The development admin APIs require fixed local-only keys. Define these once
for the commands below:

```powershell
$homeHeaders = @{"X-API-Key" = "change-me-home-admin"}
$userHeaders = @{"X-API-Key" = "change-me-user-admin"}
```

## Manual development flow: connect two agents and toggle a helper

Start the development holder (admin :8031, inbound :8010). It automatically
receives credentials and answers PP2 requests:

```powershell
docker compose up -d acapy-user
```

This connection flow originated in v0.0.1. Before sending the command in step
4, complete credential issuance below and start the configured gateway.
Connected agents are no longer implicitly authorized. For a separate guest
machine, use the [reference controller](CONTROLLER.md) and keep its `call`
process running through the proof exchange.

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
   $request = @{jsonrpc="2.0"; id=[guid]::NewGuid().ToString(); method="homeassistant.call_service"; params=@{action="turn_on"; entity_id="input_boolean.ssi_test"}} | ConvertTo-Json -Compress
   $msg = @{content=$request} | ConvertTo-Json -Compress
   Invoke-RestMethod -Uri "http://localhost:8031/connections/<connection_id>/send-message" -Method Post -Headers $userHeaders -ContentType "application/json" -Body $msg
   ```

With a valid fresh proof and matching active grant, the expected result is an
execution entry in the gateway logs (`docker compose logs gateway`) and
`input_boolean.ssi_test` turning on in Home Assistant. The Container smoke
checks cover this proof-required allowed-call flow.

## Verifiable-credential authorization with per-command proof

There's no static allowlist anymore. Instead, the home issues a
`SmartHomeAccessCredential` (a JSON-LD/`ld_proof` verifiable credential, no
ledger needed) to a connection. Each authorized command requires a fresh
ACA-Py Present Proof 2.0 DIF presentation with `Ed25519Signature2018` and a
home/command-bound random challenge. The signed challenge incorporates a hash
of `HOME_ID`, the home issuer, the command fingerprint, and a fresh random
256-bit nonce. ACA-Py drops `domain` during signing, so requests omit the
optional domain; no authorization check relies on a signed or checked
`proof.domain`. The gateway retrieves the authoritative
presentation-exchange record through ACA-Py's private Admin API, requires it
to be verified, and binds it to the same connection and pending request,
including the exact signed challenge. Webhook data alone cannot authorize a
command. The presentation's signing verification method must belong to the
VC's `did:key` subject.

The presented credential must match an exact active locally issued grant for
the connection, home, and issuer, including subject, role, permissions, and
expiry. Local `permissions`, expiry, and revocation checks remain mandatory
before HA dispatch. A valid proof does not restore a revoked or expired grant.
There is no connection-only fallback. Permissions still match entities; this
work does not add Home Assistant service/action restrictions. See
[the roadmap](ROADMAP.md) for observed checks and remaining validation.

The proof request uses exact eligible VC fingerprints in an opaque input
descriptor ID. The reference controller explicitly supplies `record_ids`
under that dynamic descriptor ID instead of relying on credential ordering.
This addresses the case where a revoked grant was selected ahead of an active
grant issued in the same second. It does not replace the verified-proof or
exact active local grant checks.

1. Both agents need a stable `did:key` identity (separate from their
   pairwise connection DID) for issuing/holding JSON-LD credentials:

   The following creation commands are for a fresh wallet. On upgrade, reuse
   the existing home issuer and holder DIDs, keys, credentials, and grants.

   ```powershell
   $homeKey = Invoke-RestMethod -Uri "http://localhost:8021/wallet/did/create" -Method Post -Headers $homeHeaders -ContentType "application/json" -Body '{"method":"key","options":{"key_type":"ed25519"}}'
   $userKey = Invoke-RestMethod -Uri "http://localhost:8031/wallet/did/create" -Method Post -Headers $userHeaders -ContentType "application/json" -Body '{"method":"key","options":{"key_type":"ed25519"}}'
   ```

   Put the home's did:key in `gateway/.env` as `HOME_ISSUER_DID`, retain a stable
   `HOME_ID`, and start the gateway with `docker compose up -d --build gateway`.
   Its authorization flow requires this configured issuer and a holder that
   can answer the per-command proof request.

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

3. Send commands using the manual development flow above, with a new RPC ID
   each time. Execution requires both a fresh verified proof bound to that
   command and an exact active grant covering the `entity_id`. Missing or
   invalid proof, expiry, revocation, or insufficient permissions must prevent
   the Home Assistant call. The controller waits up to 45 seconds for its
   reply while the proof exchange completes.

Issued credentials are stored in SQLite and survive gateway/container
restarts. Docker Compose keeps the database in the `gateway-data` named
volume. For a non-Compose deployment, set `CREDENTIAL_STORE_PATH` to the
desired database location (the default is `data/credentials.sqlite3`). Back
up that file as part of the gateway's application data.

Deleting the delivered VC from a remote wallet does not revoke the local
grant, but a wallet without the credential and its subject's signing key
cannot satisfy a new proof request. Copies or backups may still exist; revoke
the credential or the entire connection at the home to remove access after
compromise.

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

The example ID is illustrative; generate a fresh ID for each new command.
Typed JSON-RPC IDs are persistently retained per connection for 24 hours for
replay suppression, so numeric `1` and string `"1"` are distinct IDs. Duplicate
messages must not dispatch the HA action again, including across gateway
restarts. This protection is bounded to the retention window.

The gateway never retries HA dispatch after a crash. A crash during dispatch
can leave the action outcome unknown; this is not an exactly-once guarantee.
Inspect Home Assistant state before deliberately issuing a new command with
a new ID. The Container smoke and standalone lifecycle results described above
do not by themselves establish replay suppression or dispatch crash handling.

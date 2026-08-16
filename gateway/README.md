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
(:8080). Before starting:

- Copy `gateway/.env.example` to `gateway/.env` and fill in your Home
  Assistant `HA_BASE_URL` and a long-lived access token (`HA_TOKEN`).
  `gateway/.env` is gitignored — it's deployment-specific, not committed.
- Create an `input_boolean.ssi_test` helper in Home Assistant.

## v0.0.1 manual test: connect two agents and toggle a helper

1. Create an OOB invitation on the home agent:

   ```powershell
   $body = '{"handshake_protocols":["https://didcomm.org/didexchange/1.0"],"use_public_did":false}'
   $inv = Invoke-RestMethod -Uri http://localhost:8021/out-of-band/create-invitation -Method Post -ContentType "application/json" -Body $body
   ```

2. Have the user agent receive and auto-accept it:

   ```powershell
   $invJson = $inv.invitation | ConvertTo-Json -Depth 10 -Compress
   $recv = Invoke-RestMethod -Uri "http://localhost:8031/out-of-band/receive-invitation?auto_accept=true" -Method Post -ContentType "application/json" -Body $invJson
   ```

3. The home agent does **not** auto-accept incoming requests by default, so
   manually accept it (check `GET http://localhost:8021/connections` for the
   `request` connection id first):

   ```powershell
   Invoke-RestMethod -Uri "http://localhost:8021/didexchange/<connection_id>/accept-request" -Method Post
   ```

   Both agents' connections should now show `state: active` /
   `rfc23_state: completed`.

4. From the user agent, send a Basic Message on the established connection
   (use the user agent's connection id):

   ```powershell
   $msg = '{"content":"{\"action\": \"turn_on\", \"entity_id\": \"input_boolean.ssi_test\"}"}'
   Invoke-RestMethod -Uri "http://localhost:8031/connections/<connection_id>/send-message" -Method Post -ContentType "application/json" -Body $msg
   ```

The gateway logs should show it executed the command
(`docker compose logs gateway`), and `input_boolean.ssi_test` should turn on
in Home Assistant.

## v0.0.3: verifiable-credential authorization (verified working)

There's no static allowlist anymore. Instead, the home issues a
`SmartHomeAccessCredential` (a JSON-LD/`ld_proof` verifiable credential, no
ledger needed) to a connection, and the gateway checks that credential's
`permissions`/`expirationDate` before executing a command. See
`gateway/credentials.py` for the credential shape and check logic, and
`ROADMAP.md` for a known limitation (live Present Proof possession checks
aren't wired up yet — see below).

1. Both agents need a stable `did:key` identity (separate from their
   pairwise connection DID) for issuing/holding JSON-LD credentials:

   ```powershell
   $homeKey = Invoke-RestMethod -Uri "http://localhost:8021/wallet/did/create" -Method Post -ContentType "application/json" -Body '{"method":"key","options":{"key_type":"ed25519"}}'
   $userKey = Invoke-RestMethod -Uri "http://localhost:8031/wallet/did/create" -Method Post -ContentType "application/json" -Body '{"method":"key","options":{"key_type":"ed25519"}}'
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

Note: the credential store (`credentials.ISSUED`) is in-memory and is lost
when the gateway restarts — re-issue credentials after a restart if testing.


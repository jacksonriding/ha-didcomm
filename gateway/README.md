# gateway

The `ha-didcomm` gateway: receives ACA-Py webhook events, checks authorization
policy, and translates authorized commands into Home Assistant service calls.

## v0.0.1 manual test (verified working)

From the repo root:

```powershell
docker compose up -d --build
```

This starts `acapy-home` (admin API on :8021, inbound on :8000), `acapy-user`
(admin :8031, inbound :8010, representing the remote agent) and `gateway`
(:8080). Before starting:

- Copy `gateway/.env.example` to `gateway/.env` and fill in your Home
  Assistant `HA_BASE_URL` and a long-lived access token (`HA_TOKEN`).
- Copy `config/policies.example.yaml` to `config/policies.yaml`. Both
  `gateway/.env` and `config/policies.yaml` are gitignored — they're
  deployment-specific, not committed.
- Create an `input_boolean.ssi_test` helper in Home Assistant.

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

## v0.0.2: authorization allowlist (verified working)

`policy.py` now enforces `config/policies.yaml` (copy from
`config/policies.example.yaml`), mounted read-only into the container at
`/config/policies.yaml` (see `docker-compose.yml`). It maps the **home**
agent's `connection_id` for a given remote party to the `entity_id` fnmatch
patterns that party is allowed to control:

```yaml
connections:
  <home-side-connection_id>:
    allow:
      - input_boolean.ssi_test
      - light.guest_room*
```

Find the home agent's connection id for a given remote party with
`GET http://localhost:8021/connections`. Any command for a `connection_id` /
`entity_id` combination not covered by an `allow` pattern is denied — the
gateway logs `Denied <action> -> <entity_id> for connection <id>` and does
**not** call Home Assistant.

To test: send an allowed command (as in the v0.0.1 test above) and confirm it
executes; then send a command for an entity not in the allowlist (e.g.
`light.does_not_exist`) and confirm the gateway logs a denial with no
corresponding Home Assistant REST call.

The policy file is re-read on every request, so editing
`config/policies.yaml` takes effect immediately without restarting the
gateway.


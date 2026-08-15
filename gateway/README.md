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
(:8080). Fill in `gateway/.env` first (copy from `.env.example`) with your
Home Assistant `HA_BASE_URL` and a long-lived access token (`HA_TOKEN`), and
create an `input_boolean.ssi_test` helper in Home Assistant.

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


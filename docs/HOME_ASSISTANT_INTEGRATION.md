# Home Assistant custom integration

The `ha_didcomm` custom integration shows each DIDComm connection and issued
access credential as an entity in Home Assistant. It polls the gateway's
read-only status API every 30 seconds and provides administrator-only actions
for invitation, issuance, expiry, and revocation.

## Install

Copy the integration directory into Home Assistant's configuration directory:

```text
custom_components/ha_didcomm/
```

The resulting path inside Home Assistant must be:

```text
/config/custom_components/ha_didcomm/manifest.json
```

Restart Home Assistant, then open **Settings > Devices & services > Add
integration**, search for **ha-didcomm**, and enter the gateway URL and the
same owner token configured on the app or standalone gateway. For a default
Home Assistant app installation, use:

```text
https://homeassistant.local:8000
```

Use the HTTPS hostname covered by the configured certificate. A standalone
deployment normally uses the value of `ACAPY_PUBLIC_ENDPOINT`, such as
`https://home.example:8443`.

Add another config entry for each additional home gateway. Entries are keyed
by the gateway issuer DID, so the same Home Assistant instance can display
connections and credentials from multiple homes without entity ID collisions.
See [multi-home delegated access](MULTI_HOME.md) for the isolation model.

## Entities

- Each ACA-Py connection becomes a sensor whose state is the connection state.
- Each issued credential becomes an enum sensor with `active`, `expired`,
  `revoked`, or `invalid` state.
- Credential entities are grouped under their connection device and include
  role, permissions, subject DID, issuance, expiry, and revocation metadata.
- Credential attributes include the issuing home ID and issuer DID.
- New connections and credentials are discovered without reloading the
integration.

## Owner actions

The integration registers these actions for Home Assistant administrators:

- `ha_didcomm.create_invitation` creates a single-use invitation and returns
  its URL.
- `ha_didcomm.issue_credential` grants one or more entity patterns for a
  required duration between 1 and 8760 hours.
- `ha_didcomm.revoke_credential` revokes one credential exchange ID.
- `ha_didcomm.revoke_connection` revokes all credentials for a connection.

Every action requires `config_entry_id`, which selects the home gateway. Find
connection IDs, subject DIDs, and credential exchange IDs in the integration's
sensor attributes. For example, in **Developer tools > Actions**:

```yaml
action: ha_didcomm.issue_credential
data:
  config_entry_id: 01EXAMPLEENTRY
  connection_id: connection-id-from-the-sensor
  subject_did: did:key:guest-holder-did
  permissions:
    - light.guest_*
    - switch.guest_room
  role: guest
  duration_hours: 24
```

Request response data when creating an invitation or issuing a credential to
use `invitation_url`, `cred_ex_id`, or `expires_at` in an automation. Entries
upgraded from integration version 0.2 remain read-only until reconfigured with
an owner token.

The TLS proxy exposes sanitized `/status` and `/health` routes plus the
bearer-authenticated `/owner/` surface alongside the DIDComm listener.
Connection identifiers and access scopes are still operational metadata.
Webhook, legacy mutation, and ACA-Py Admin routes remain private.

## Development

With the development stack running, verify the status surface directly:

```powershell
docker compose up -d --build gateway
Invoke-RestMethod http://localhost:8090/status
```

The development stack deliberately uses loopback HTTP. Packaged deployments
require HTTPS.

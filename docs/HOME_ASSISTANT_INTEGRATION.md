# Home Assistant custom integration

The `ha_didcomm` custom integration shows each DIDComm connection and issued
access credential as an entity in Home Assistant. It polls the gateway's
read-only status API every 30 seconds; it cannot issue or revoke credentials.

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
integration**, search for **ha-didcomm**, and enter the status API URL. For a
default app or standalone installation on the same host, use:

```text
http://homeassistant.local:8090
```

Use the Home Assistant host's LAN IP instead if that name does not resolve
from the Home Assistant Core container.

## Entities

- Each ACA-Py connection becomes a sensor whose state is the connection state.
- Each issued credential becomes an enum sensor with `active`, `expired`,
  `revoked`, or `invalid` state.
- Credential entities are grouped under their connection device and include
  role, permissions, subject DID, issuance, expiry, and revocation metadata.
- New connections and credentials are discovered without reloading the
  integration.

Port 8090 exposes only sanitized, read-only status and health routes. Keep it
on a trusted local network because connection identifiers and access scopes
are still operational metadata. Mutation and webhook routes remain on the
internal gateway port 8080.

## Development

With the development stack running, verify the status surface directly:

```powershell
docker compose up -d --build gateway
Invoke-RestMethod http://localhost:8090/status
```

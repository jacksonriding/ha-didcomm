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
default Home Assistant app installation, use:

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

The TLS proxy exposes sanitized `/status` and `/health` routes alongside the
DIDComm listener. Connection identifiers and access scopes are still
operational metadata. Mutation, webhook, and ACA-Py Admin routes remain on the
private container network.

## Development

With the development stack running, verify the status surface directly:

```powershell
docker compose up -d --build gateway
Invoke-RestMethod http://localhost:8090/status
```

The development stack deliberately uses loopback HTTP. Packaged deployments
require HTTPS.

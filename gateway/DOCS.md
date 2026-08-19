# ha-didcomm Home Assistant app

This experimental app runs ACA-Py and the ha-didcomm gateway together. It
uses Home Assistant's internal Supervisor proxy and `SUPERVISOR_TOKEN`; no
long-lived Home Assistant access token is required.

## Configuration

- `public_endpoint`: HTTPS URL remote DIDComm agents use to reach port 8000.
  Its hostname must match the configured certificate.
- `home_id`: Identifier embedded in access credentials for this home.
- `log_level`: ACA-Py logging level.
- `certfile`: Certificate-chain filename from Home Assistant's `/ssl` share.
- `keyfile`: Matching private-key filename from Home Assistant's `/ssl` share.

The ACA-Py wallet, generated issuer DID, wallet key, and gateway credential
database are stored under `/data` and included in cold Home Assistant backups.

Port 8000 terminates TLS and carries DIDComm traffic plus the sanitized
`/status` and `/health` routes used by the optional Home Assistant custom
integration. ACA-Py's API-key-protected Admin API, inbound transport, status
service, and gateway webhook listener bind to loopback inside the app
container.

## Installation from this repository

Add `https://github.com/jacksonriding/ha-didcomm` as a custom app repository,
install **ha-didcomm**, select certificate files from `/ssl`, configure the
matching HTTPS `public_endpoint`, and start it.

To display connections and credentials as Home Assistant entities, follow the
[custom integration installation guide](../docs/HOME_ASSISTANT_INTEGRATION.md)
and configure its status URL as `https://homeassistant.local:8000` or the
certificate-covered hostname in `public_endpoint`.

The app refuses to start when `public_endpoint` is not HTTPS or when its
certificate files are missing. ACA-Py's Admin API key is generated once,
stored under `/data`, and reused across upgrades.

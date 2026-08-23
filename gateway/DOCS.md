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
- `owner_api_token`: Random token of at least 32 characters used only by Home
  Assistant's administrator-only owner actions. Generate one with
  `python -c "import secrets; print(secrets.token_urlsafe(32))"`.

The ACA-Py wallet, generated issuer DID, wallet key, and gateway credential
database are stored under `/data` and included in cold Home Assistant backups.

Port 8000 terminates TLS and carries DIDComm traffic plus the sanitized
`/status` and `/health` routes plus the bearer-authenticated `/owner/` routes
used by the optional Home Assistant custom integration. ACA-Py's
API-key-protected Admin API, inbound transport, status service, legacy owner
routes, and gateway webhook listener bind to loopback inside the app container.

## Installation from this repository

Add `https://github.com/jacksonriding/ha-didcomm` as a custom app repository,
install **ha-didcomm**, select certificate files from `/ssl`, configure the
matching HTTPS `public_endpoint`, set a strong `owner_api_token`, and start it.

To display connections and credentials as Home Assistant entities, follow the
[custom integration installation guide](../docs/HOME_ASSISTANT_INTEGRATION.md)
and configure its gateway URL as `https://homeassistant.local:8000` or the
certificate-covered hostname in `public_endpoint`, using the same owner token.

The same Home Assistant instance may add multiple independently operated
gateways. Each home must use its own `home_id`, issuer DID, wallet, and data
volume. See the [multi-home guide](../docs/MULTI_HOME.md).

The app refuses to start when `public_endpoint` is not HTTPS or when its
certificate files are missing. ACA-Py's Admin API key is generated once,
stored under `/data`, and reused across upgrades. An absent or weak owner token
leaves status monitoring available but disables every `/owner/` operation.

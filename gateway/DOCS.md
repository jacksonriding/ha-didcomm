# ha-didcomm Home Assistant app

This experimental app runs ACA-Py and the ha-didcomm gateway together. It
uses Home Assistant's internal Supervisor proxy and `SUPERVISOR_TOKEN`; no
long-lived Home Assistant access token is required.

## Configuration

- `public_endpoint`: URL remote DIDComm agents use to reach port 8000. Use a
  LAN address such as `http://192.168.1.10:8000`, or a TLS-protected public
  endpoint for access outside the home network.
- `home_id`: Identifier embedded in access credentials for this home.
- `log_level`: ACA-Py logging level.

The ACA-Py wallet, generated issuer DID, wallet key, and gateway credential
database are stored under `/data` and included in cold Home Assistant backups.

Port 8000 is the only exposed port. ACA-Py's Admin API and the gateway webhook
listener bind to loopback inside the app container.

## Installation from this repository

Add `https://github.com/jacksonriding/ha-didcomm` as a custom app repository,
install **ha-didcomm**, configure `public_endpoint`, and start it.

This app is experimental. The public DIDComm endpoint does not yet configure
TLS automatically; use it only on a trusted LAN unless you provide a secure
reverse proxy.

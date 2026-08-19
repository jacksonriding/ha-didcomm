# Changelog

## 0.0.8

- Support independently scoped guest credentials across multiple homes.
- Expose credential home and issuer metadata to the Home Assistant integration.
- Reject stored credentials whose home or issuer does not match this gateway.

## 0.0.7

- Require API-key authentication for the internal ACA-Py Admin API.
- Terminate TLS in the app before forwarding DIDComm or status requests.
- Require Supervisor-managed certificate and private-key files.

## 0.0.6

- Add a separate read-only status API for the Home Assistant integration.
- Keep webhook and owner mutation routes isolated from the published UI port.

## 0.0.5

- Initial experimental Home Assistant app packaging.
- Bundle ACA-Py and the gateway in one persistent container.
- Use the Supervisor Home Assistant API proxy instead of a long-lived token.

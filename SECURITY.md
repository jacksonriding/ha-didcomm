# Security policy

## Project status

ha-didcomm is experimental software and has not received an independent
security audit. It can trigger Home Assistant service calls and should not yet
be relied on as the only access-control layer for locks, alarms, garage doors,
medical equipment, or other safety-critical devices.

The current authorization design persistently associates issuer-side
credential records with DIDComm connections. It does not yet require a fresh
proof of credential possession for each command. See the known limitation in
[the roadmap](docs/ROADMAP.md).

Only the latest code on the `main` branch currently receives security fixes.
There is no stable supported release series yet.

## Reporting a vulnerability

Please do not open a public issue for a suspected vulnerability.

Use GitHub's **Report a vulnerability** form in the repository's Security tab.
If private vulnerability reporting is unavailable, open a public issue that
asks the maintainer to establish a private reporting channel, but do not
include vulnerability details in that issue.

Include:

- the affected version or commit;
- deployment type (Home Assistant app, standalone Compose, or development);
- reproduction steps or a proof of concept;
- the likely impact; and
- any suggested mitigation.

Remove tokens, keys, credentials, DIDs, invitations, certificates, addresses,
and personal Home Assistant data before sending a report. The maintainer will
acknowledge receipt when possible and coordinate disclosure after a fix is
available. Please allow a reasonable remediation period before publication.

## Deployment expectations

- Expose only the documented TLS proxy port.
- Keep ACA-Py's Admin API, gateway webhook, and owner mutation routes private.
- Use unique, randomly generated wallet and Admin API keys.
- Use a trusted TLS certificate whose hostname matches the public endpoint.
- Back up `/data` or the named data volumes securely; they contain identity
  material and authorization state.
- Grant narrow entity patterns with short expiries and revoke unused access.

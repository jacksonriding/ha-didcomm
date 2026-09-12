# Security policy

## Project status

ha-didcomm is experimental software and has not received an independent
security audit. It can trigger Home Assistant service calls and should not yet
be relied on as the only access-control layer for locks, alarms, garage doors,
medical equipment, or other safety-critical devices.

The implemented per-command proof authorization contract requires
a fresh ACA-Py Present Proof 2.0 DIF presentation for every authorized command,
using `Ed25519Signature2018` and a home/command-bound random challenge. The
signed challenge incorporates a hash of `HOME_ID`, the home issuer, the
command fingerprint, and a fresh random 256-bit nonce. ACA-Py drops `domain`
during signing: the request omits the optional domain, and authorization does
not depend on `proof.domain` being signed or checked.
Observed Docker Container smoke checks passed for DID exchange, credential
issuance, fresh signed proof before an allowed HA call, and denial of
disallowed, revoked, and missing-wallet-VC commands with exact-fingerprint
selection enabled. The full standalone lifecycle, including backup/restore,
and the app `0.0.12` Docker rebuild passed. Version and Compose checks passed.
Physical HA OS validation has not been performed. These checks do not
establish production security or replace an independent audit. See
[the roadmap](docs/ROADMAP.md) for remaining validation.

The gateway must retrieve the authoritative presentation-exchange record from
ACA-Py's private Admin API, require successful verification, and bind it to
the same DIDComm connection and pending request, including the exact signed
challenge. A webhook notification alone is not proof of verification. The
presentation's signing verification method must belong to the VC's `did:key`
subject. Possession alone is insufficient: the presented credential must
match an exact active locally issued grant for that connection, home, and
issuer, with subject, role, permissions, and expiry matching the grant.
Local expiry and revocation checks remain mandatory before HA dispatch.

Proof selection uses exact eligible VC fingerprints in an opaque input
descriptor ID. The reference controller explicitly supplies `record_ids`
under that dynamic descriptor ID. This addresses selection of a revoked grant
ahead of an active grant issued in the same second; the authoritative proof
and exact active local grant checks still apply before dispatch.

Typed JSON-RPC IDs are persistently tracked per connection for 24 hours to
suppress replays and duplicate dispatch; numeric and string IDs are distinct.
The gateway never retries HA dispatch after a crash. An interrupted dispatch
can have an unknown outcome, so inspect HA state before issuing a new command
with a new ID. This is not an exactly-once execution guarantee.

Grants remain entity-scoped; this work does not add service/action permissions.
Protect controller wallets, holder keys, and connection state, and revoke
compromised grants at the home. Other wallets must answer PP2 requests; there
is no connection-only authorization fallback when proof is missing or invalid.

The selected deployment image is official ACA-Py `py3.13-1.6.2rc0`, pinned by
digest and containing PR #4217. This release candidate is selected because the
stable rolling `py3.13-1.6-lts` tag still serves the old July 28 registry image,
even after pulling. Use the [exact deployment pin and rebuild instructions](docs/GATEWAY.md#aca-py-deployment-pin-coordinator)
for all Compose agents and the bundled app. Upgrade both home and controller,
preserving wallet volumes, keys, existing credentials, and gateway state.
The pin does not establish runtime acceptance. The default
proof timeout is 30 seconds; the reference controller waits 45 seconds.

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
- Keep ACA-Py's Admin API, gateway webhook, and legacy `/admin` mutation routes
  private. Publish `/owner/` only through the documented TLS proxy.
- Use unique, randomly generated wallet, Admin API, and owner API secrets. The
  owner token must contain at least 32 characters.
- Use a trusted TLS certificate whose hostname matches the public endpoint.
- Back up `/data` or the named data volumes securely; they contain identity
  material and authorization state.
- Grant narrow entity patterns with short expiries and revoke unused access.
  Reissuing the same connection, subject DID, role, and permission set
  is rejected while an equivalent grant remains active. Revoke it before an
  intentional replacement; broader or different grants remain independent.

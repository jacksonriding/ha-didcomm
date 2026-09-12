# Changelog

## 0.0.12

- Implement mandatory fresh ACA-Py Present Proof 2.0 DIF proof for each
  authorized command using `Ed25519Signature2018` and a home/command-bound
  random challenge incorporating a hash of `HOME_ID`, the home issuer, the
  command fingerprint, and a fresh random 256-bit nonce. ACA-Py drops `domain`
  during signing, so omit the optional request domain and make no signed or
  checked `proof.domain` claim. Require an authoritative verified private Admin API
  record bound to the same connection and pending request, and a presentation
  signing verification method belonging to the VC's `did:key` subject.
- Retain exact active local grant matching and expiry/revocation checks before
  HA dispatch. This work does not add service/action permission restrictions.
- Fix selection of a revoked grant ahead of an active grant issued in the
  same second by using exact eligible VC fingerprints in an opaque input
  descriptor ID. The reference controller explicitly supplies `record_ids`
  under the dynamic descriptor ID.
- Implement persistent typed JSON-RPC ID replay suppression for 24 hours and
  never retry HA dispatch after a crash; an interrupted dispatch may have an
  unknown outcome.
- Update the reference-controller flow to explicitly send the holder's
  `dif.issuer_id` for its pending command and wait up to 45 seconds, with a
  default proof timeout of 30 seconds. Other
  wallets must respond to PP2; development `acapy-user` presentation-request
  auto-response is enabled.
- Replace the old connection-only authorization description and deferred
  signing blocker with the per-command proof contract and merged ACA-Py fixes:
  [#4196 (main)](https://github.com/openwallet-foundation/acapy/pull/4196),
  [#4216 (1.3 LTS)](https://github.com/openwallet-foundation/acapy/pull/4216), and
  [#4217 (1.6 LTS)](https://github.com/openwallet-foundation/acapy/pull/4217).
- Document the official ACA-Py deployment pin applied in all three Compose
  files and the bundled app Dockerfile:
  `py3.13-1.6.2rc0@sha256:41bd97050a16040a549104bafc92636ee0739bb082f2af27b27b7a5c142ccdaa`,
  revision `b7aa96d271267d3edb7d78fa52013a5c618d4fea`, containing PR #4217.
  The RC is intentional because the stable rolling `py3.13-1.6-lts` registry
  tag still serves the old July 28 image even after pulling. Include home and
  controller rebuild instructions that preserve wallet volumes, keys, and
  existing credentials in
  the [gateway guide](../docs/GATEWAY.md#aca-py-deployment-pin-coordinator).
  Upgrading both home and controller is required; existing credentials do not
  need to be reissued.
- Record passing Docker Container smoke coverage for DID exchange, credential
  issuance, fresh signed proof before an allowed HA call, and denial of
  disallowed, revoked, and missing-wallet-VC commands with exact-fingerprint
  selection enabled (exit 0, including cleanup). The full standalone
  lifecycle passed, including backup/restore and post-restore owner operations.
  The app `0.0.12` Docker rebuild and version/Compose checks passed.
  See the [roadmap](../docs/ROADMAP.md) for
  remaining validation. Physical HA OS remains unvalidated; no
  production-security or independent-audit claim is made.

## 0.0.11

- Add an isolated standalone lifecycle test covering fresh installation,
  container replacement, cold backup, destructive volume loss, restore, and
  post-restore owner operations.
- Document repeatable standalone and Home Assistant OS validation procedures,
  including the identity and authorization state that must survive.
- Minimize the public `/status` response and move detailed connection,
  credential, DID, and permission metadata behind owner authentication at
  `/owner/status`.
- Reject duplicate active grants for the same connection, subject, role, and
  permission scope before ACA-Py mints another credential.
- Harden reference-controller onboarding by preserving the wallet DID,
  accepting copied Home Assistant action responses, ignoring `.env.controller`,
  and using wallet-key argument forms that tolerate generated secrets.

## 0.0.10

- Add bearer-authenticated owner endpoints for invitation creation, expiring
  credential issuance, and credential or connection revocation.
- Add native, administrator-only Home Assistant actions for the complete owner
  workflow while preserving read-only upgrades.
- Publish owner endpoints through the TLS proxy without exposing ACA-Py's Admin
  API, and cover the authenticated workflow in automated tests.

## 0.0.9

- Add a persistent reference-controller Compose stack and CLI for accepting
  invitations, managing a holder DID, and sending commands with reply handling.
- Exercise invitation, credential issuance, authorization, denial, and
  revocation in an automated Docker smoke test.
- License the project under Apache-2.0 and add contribution, conduct, and
  security policies.
- Add gateway test and Compose validation workflows for pull requests.
- Add reproducible development dependencies and automated release-version
  consistency checks.
- Add structured issue templates and publish the next usability and security
  milestones.

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

# Roadmap

**Next app release: 0.0.12 (unreleased; release tag `v0.0.12` pending).**
The Home Assistant app configuration version is now `0.0.12` so existing
installations can receive the update. The changelog uses that version
for release-check compatibility; this does not mean the release or tag has
been published. The custom integration version is unchanged. Observed checks
and remaining runtime validation are recorded below.

Guiding principle: don't touch Home Assistant internals, don't touch ACA-Py
internals. Compose them through their existing REST/webhook APIs from a small
gateway service. Add complexity one milestone at a time.

Scope boundary — keep it here, don't creep further down the stack:

```
DID / DIDComm / VC
        │
Gateway (this repo) — authorization + translation
        │
Home Assistant REST/WebSocket API
        │
Zigbee / Matter / Wi-Fi / etc. (untouched)
```

## v0.0.1 — Prove the wire works

**Goal:** *"By the end of v0.0.1, I can establish a DIDComm connection and
toggle a Home Assistant helper through it."*

**Status: done (2026-08-16).**

- [x] `compose.yml` running a single ACA-Py agent (API-key-protected admin API
      bound to localhost)
- [x] Second ACA-Py agent (or the ACA-Py demo agent) to act as the "remote user"
- [x] Out-of-Band invitation + DID Exchange between the two agents using
      `did:peer:4` (no ledger)
- [x] Home Assistant instance reachable with a long-lived access token
      (existing HA install, or a throwaway dev instance)
- [x] `input_boolean.ssi_test` helper created in Home Assistant
- [x] Gateway (`gateway/`) that:
  - subscribes to ACA-Py webhooks
  - receives a Basic Message: `{"action": "turn_on", "entity_id": "input_boolean.ssi_test"}`
  - calls Home Assistant `POST /api/services/input_boolean/turn_on`
- [x] No authorization logic yet — every connected agent is trusted
- [x] Manual end-to-end test documented in `docs/GATEWAY.md`

**Out of scope:** credentials, permissions, revocation, physical devices, any UI.


## v0.0.2 — Static authorization

**Status: done (2026-08-16).**

- [x] Connection-based allowlist config (`config/policies.yaml`):
      map `connection_id`/DID → allowed `entity_id`s (fnmatch patterns)
- [x] Gateway rejects commands for entities not in the caller's allowlist
- [x] Support more than one remote agent connected at once (allowlist keyed
      by connection_id, one entry per connection)
- [x] Basic structured logging of allow/deny decisions


## v0.0.3 — Verifiable credentials replace the static allowlist

**Status: per-command proof implemented; Container smoke with exact-fingerprint
selection, full standalone lifecycle, app 0.0.12 Docker rebuild, and
version/Compose checks passed.**

- [x] Define a `SmartHomeAccessCredential` schema (role, home id, permissions,
      optional expiry) as a JSON-LD (`ld_proof`) credential, so no ledger or
      schema registration is needed
- [x] Home agent issues credentials to remote agents via ACA-Py Issue
      Credential 2.0 (`gateway/src/ha_didcomm/credentials.py` +
      `POST /admin/issue-credential`)
- [x] Expiry enforced in the gateway (`credentials.py::_is_expired`)
- [x] Permission matching by fnmatch pattern against `credentialSubject.permissions`
- [x] Manually tested: allowed entity executes, disallowed entity denied,
      expired credential denied

**Upstream signing blocker fixed; deployment image selected.** The
ACA-Py DIF holder-signing fix merged in
[PR #4196 (main)](https://github.com/openwallet-foundation/acapy/pull/4196),
[PR #4216 (1.3 LTS)](https://github.com/openwallet-foundation/acapy/pull/4216), and
[PR #4217 (1.6 LTS)](https://github.com/openwallet-foundation/acapy/pull/4217).
The old failure produced unsigned presentations when holder signing ignored
the explicit `issuer_id`. The selected official image is
`ghcr.io/openwallet-foundation/acapy-agent:py3.13-1.6.2rc0@sha256:41bd97050a16040a549104bafc92636ee0739bb082f2af27b27b7a5c142ccdaa`,
with source revision `b7aa96d271267d3edb7d78fa52013a5c618d4fea` containing
PR #4217. This release candidate is needed because the stable rolling
`py3.13-1.6-lts` tag still serves the old July 28 registry image even after
pulling. Use this pin for all Compose agents and the bundled app; see the
[rebuild instructions](GATEWAY.md#aca-py-deployment-pin-coordinator).
The pin is applied in `compose.yml`, `compose.standalone.yml`,
`compose.controller.yml`, and the add-on stage of `gateway/Dockerfile`.
Upgrade both home and controller while retaining wallet volumes, keys,
existing credentials, and local grants.

**Observed runtime checks (coordinator report):** Docker Container smoke passed
with the pinned official RC image, covering DID exchange, credential issuance,
fresh signed proof before a permitted HA call, and denial of disallowed,
revoked, and missing-wallet-VC commands with exact-fingerprint selection
enabled. The smoke run exited successfully (`0`), including cleanup.
The full standalone lifecycle test
passed, covering fresh installation, container replacement, cold backup,
volume loss, restore, and post-restore owner operations. The add-on Docker
rebuild as `0.0.12` passed, as did version and Compose checks. These establish
build/configuration results, not HA OS installation or runtime.
Physical Home Assistant OS remains unvalidated.

Selection uses exact eligible VC fingerprints in an opaque input descriptor
ID, with the reference controller explicitly submitting `record_ids` under
the dynamic ID. This fixes selection of a revoked grant ahead of an active
grant issued in the same second.

The implementation requires a fresh Present Proof 2.0 DIF presentation for
each authorized command, signed with `Ed25519Signature2018` over a
home/command-bound random challenge. The challenge incorporates a hash of
`HOME_ID`, the home issuer, the command fingerprint, and a fresh random
256-bit nonce. ACA-Py drops `domain` during signing, so the request omits the
optional domain; there is no signed or checked `proof.domain` claim.
The gateway retrieves the authoritative
private Admin API record, requires it to be verified for the same connection
and pending request, and checks that the signing verification method belongs
to the VC's `did:key` subject. The credential must match an exact active local
grant; local expiry and revocation checks remain mandatory before dispatch.
The reference controller explicitly sends the holder's `dif.issuer_id` for
the pending command and waits up to 45 seconds; the default proof timeout is
30 seconds. Other wallets must respond to
PP2; the development `acapy-user` has
`--auto-respond-presentation-request` enabled.

- [x] Implement mandatory per-command Present Proof-based possession verification
- [x] Select the official patched ACA-Py RC image and immutable deployment pin
- [x] Docker Container smoke covering proof-required allowed calls and
      disallowed, revoked, and missing-wallet-VC denial
- [x] Full standalone lifecycle, including backup/restore and owner operations
- [x] App 0.0.12 Docker rebuild
- [x] Version and Compose checks
- [x] Implement exact eligible VC selection and explicit dynamic `record_ids`
- [x] Smoke with exact-fingerprint selection (exit 0, including cleanup)
- [x] Enable development `acapy-user` presentation-request auto-response
- [x] Persist issued credentials in a local SQLite store, backed by a Docker
      named volume so authorization survives gateway/container restarts
- [x] Basic issuer-side revocation check for individual credentials and all
      credentials associated with a connection


## v0.0.4 — Onboarding UX

- [x] QR code (OOB invitation) rendered somewhere accessible (CLI first, HA
      dashboard card later) for adding a new guest connection
- [x] Gateway owner CLI to:
  - [x] see connected agents
  - [x] issue a scoped/expiring credential to a connection
  - [x] revoke a credential/connection
- [x] JSON-RPC 2.0 command/response schema over Basic Message, with structured
      authorization and execution errors (no maintained ACA-Py RPC plugin was
      available in the official plugin repository)

## v0.0.5+ — Packaging for real Home Assistant users

- [x] Experimental Home Assistant Add-on (App) bundling ACA-Py + gateway, using the
      Supervisor API proxy / `SUPERVISOR_TOKEN` so no manual API key setup
- [x] Standalone Docker Compose distribution for Home Assistant Container users
- [x] Proper Home Assistant custom integration with Config Flow, showing
      connections/credentials as entities in the UI
- [x] Harden ACA-Py deployment: admin API key auth, TLS, no insecure mode
- [x] Multi-home / delegated access scenarios (guest visiting a different home):
  independently scoped home/issuer credentials, multiple Home Assistant config
  entries, cross-home isolation tests, and an operator guide

## v0.0.9 — Open-source foundation

**Status: implementation complete; release pending.**

- [x] Adopt an OSI-approved license (Apache-2.0)
- [x] Add contribution, conduct, and responsible-disclosure policies
- [x] Run gateway tests, version checks, Python compilation, and Compose
      validation in GitHub Actions
- [x] Add structured bug and feature request templates and a pull request
      checklist
- [x] Add automated dependency-update configuration
- [x] Check gateway release metadata against its changelog and release tag
- [ ] Publish the `v0.0.12` tag and GitHub release after CI passes

The Home Assistant app and custom integration are independently installable
components and retain independent semantic versions. A repository release must
match the app version in `gateway/config.yaml`; `scripts/check_versions.py`
enforces this convention for release tags.

## v0.1.0 — Usable alpha

**Goal:** a new user can complete one documented path from installation to a
revoked guest command without needing to understand ACA-Py's Admin API.

- [x] Publish one supported remote-controller or reference-agent workflow
      (`compose.controller.yml` and `docs/CONTROLLER.md`)
- [x] Add an automated end-to-end smoke test covering invitation, connection,
      credential issuance, authorized command, denial, and revocation
      (`scripts/docker_smoke_test.py`)
- [x] Provide Home Assistant owner controls for invitation, issuance, expiry,
      and revocation instead of requiring Docker CLI commands
- [ ] Test fresh installation, upgrade, backup, and restore on Home Assistant OS
      and standalone Container deployments
  - [x] Automate the destructive standalone lifecycle in an isolated Docker
        project (`scripts/docker_lifecycle_test.py`)
  - [x] Publish a repeatable Home Assistant OS validation checklist
        (`docs/DEPLOYMENT_VALIDATION.md`)
  - [ ] Record a successful checklist run on physical Home Assistant OS
- [ ] Publish a compatibility matrix for Home Assistant, ACA-Py, Python,
      architectures, and tested remote agents
- [ ] Write a short troubleshooting guide based on clean-machine testing

## v0.2.0 — Security beta

**Goal:** close the known authorization gaps and document the resulting trust
model before recommending use beyond experimentation.

- [x] Implement a mandatory fresh PP2 DIF credential-possession proof for every
      authorized command; Container smoke covers allowed and denied requests
- [x] Pin all three Compose files and the app Dockerfile to the patched RC image
- [x] Complete Container smoke and standalone lifecycle checks recorded above
- [ ] Scope grants by Home Assistant service/action as well as entity
- [x] Implement persistent typed JSON-RPC ID replay suppression for 24 hours;
      never retry HA dispatch after a crash
- [x] Reject equivalent active grants before sending a replacement VC to the
      remote wallet
- [x] Minimize the public status API and require owner authentication for
      connection, DID, credential, and permission details
- [ ] Document abuse cases, trust boundaries, key compromise, backup exposure,
      and recovery in a threat model
- [ ] Obtain an independent security review and resolve high-severity findings

## Non-goals (for now)

- Public ledger / blockchain-anchored DIDs
- Making every individual Zigbee/Matter device SSI-aware
- Mobile wallet app (rely on existing Aries-compatible wallets/agents)
- Production-grade key management

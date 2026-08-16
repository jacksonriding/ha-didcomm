# Roadmap

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

- [x] `docker-compose.yml` running a single ACA-Py agent (`--admin-insecure-mode`
      for local dev only, admin API bound to localhost)
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
- [x] Manual end-to-end test documented in `gateway/README.md`

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

**Status: mostly done (2026-08-16) — see known limitation below.**

- [x] Define a `SmartHomeAccessCredential` schema (role, home id, permissions,
      optional expiry) as a JSON-LD (`ld_proof`) credential, so no ledger or
      schema registration is needed
- [x] Home agent issues credentials to remote agents via ACA-Py Issue
      Credential 2.0 (`gateway/credentials.py` + `POST /admin/issue-credential`)
- [x] Expiry enforced in the gateway (`credentials.py::_is_expired`)
- [x] Permission matching by fnmatch pattern against `credentialSubject.permissions`
- [x] Manually tested: allowed entity executes, disallowed entity denied,
      expired credential denied

**Known limitation — deferred:** the original design asked the remote party
to *prove current possession* of the credential per-command via ACA-Py's
Present Proof 2.0 (DIF Presentation Exchange + LD-proof signing). That hit a
real bug/limitation in ACA-Py 1.6: `DIFPresFormatHandler.create_pres` always
passes `is_holder_override=True`, which makes `DIFPresExchHandler.create_vp`
ignore any explicit `issuer_id` and re-derive the signing DID itself via
`get_sign_key_credential_subject_id` — that derivation didn't reliably
resolve our `did:key` credential subjects, so presentations came back
unsigned (`verified: false`, `"presentation must contain proof"`), both with
`--auto-respond-presentation-request` and with a manual
`send-presentation` call including an explicit `issuer_id`.

Current behaviour instead: the gateway (as issuer) remembers which
credentials it issued to which connection in memory
(`credentials.ISSUED`), and checks *those* for expiry/permissions on each
command. This is still real VC issuance over DIDComm, just without a live
possession proof per action. Revisit in a later milestone — options to
investigate: a newer/older ACA-Py version, the `anoncreds-2023`/`vc_di`
presentation path instead of `dif`/`ld_proof`, or a mediator-free direct
`BasicMessage`-transported credential handoff the gateway verifies itself
with a local JSON-LD signature library instead of ACA-Py's present-proof
pipeline.

- [ ] Live Present Proof-based possession verification (deferred, see above)
- [ ] Persist issued credentials (currently in-memory, lost on gateway restart)
- [ ] Basic revocation check


## v0.0.4 — Onboarding UX

- [ ] QR code (OOB invitation) rendered somewhere accessible (CLI first, HA
      dashboard card later) for adding a new guest connection
- [ ] Simple CLI or minimal web UI in the gateway for the owner to:
  - see connected agents
  - issue a scoped/expiring credential to a connection
  - revoke a credential/connection
- [ ] `RPC`-style command schema instead of ad-hoc JSON over Basic Message
      (evaluate the ACA-Py DIDComm RPC plugin here)

## v0.0.5+ — Packaging for real Home Assistant users

- [ ] Home Assistant Add-on (App) bundling ACA-Py + gateway, using the
      Supervisor API proxy / `SUPERVISOR_TOKEN` so no manual API key setup
- [ ] Standalone Docker Compose distribution for Home Assistant Container users
- [ ] Proper Home Assistant custom integration with Config Flow, showing
      connections/credentials as entities in the UI
- [ ] Harden ACA-Py deployment: admin API key auth, TLS, no insecure mode
- [ ] Multi-home / delegated access scenarios (guest visiting a different home)

## Non-goals (for now)

- Public ledger / blockchain-anchored DIDs
- Making every individual Zigbee/Matter device SSI-aware
- Mobile wallet app (rely on existing Aries-compatible wallets/agents)
- Production-grade key management

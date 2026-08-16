# ha-didcomm

**A decentralised identity and access-control gateway for Home Assistant.**

`ha-didcomm` lets a Home Assistant instance establish encrypted, peer-to-peer
[DIDComm](https://didcomm.org/) connections with other agents (family members,
guests, other homes) using [Hyperledger Aries Cloud Agent Python (ACA-Py)](https://github.com/hyperledger/aries-cloudagent-python).
Instead of usernames/passwords or long-lived tokens, access is granted through
verifiable credentials that a controller/gateway maps onto Home Assistant
service calls.

No cloud identity provider. No public ledger required (pairwise `did:peer`
DIDs are enough). No third-party smart-home account.

## Why

Home Assistant already has users, groups and long-lived tokens for local
control. What it doesn't have is a good story for **portable, delegated,
cryptographically verifiable access** — e.g. handing a friend, a house-sitter,
or an Airbnb guest a time-boxed, scoped credential without creating them a
Home Assistant account.

`ha-didcomm` explores integrating ACA-Py with Home Assistant to provide that:

- Decentralised identities (DIDs) instead of accounts
- DIDComm as the secure transport between identities
- Verifiable credentials as the authorization mechanism
- Home Assistant as the thing actually being controlled

See [ROADMAP.md](ROADMAP.md) for the implementation plan and current status.

## Architecture (target)

```
Remote Agent (user/guest)
        │  DIDComm (did:peer)
        ▼
   ACA-Py agent  ──webhooks──►  gateway (this repo)  ──REST──►  Home Assistant
        ▲                              │
        └──────── Admin API ◄──────────┘
```

The gateway is a small Python service that:
1. Receives ACA-Py webhook events (new connections, messages, credential issuance)
2. Enforces authorization policy (verifiable credentials issued per connection)
3. Translates authorized commands into Home Assistant REST API calls

## Status

v0.0.3 done: a DIDComm connection between two ACA-Py agents (`did:peer`, no
ledger) can toggle a Home Assistant helper entity, gated by a verifiable
credential (JSON-LD, no ledger) the home issues to that connection. See
[ROADMAP.md](ROADMAP.md) for the full milestone plan, a known limitation
around live credential-possession proofs, and what's next.

## Getting started (dev)

See [ROADMAP.md](ROADMAP.md) for milestones and [gateway/README.md](gateway/README.md)
for the gateway service itself, including the manual v0.0.1 test steps.

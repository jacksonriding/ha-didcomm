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

See [the roadmap](docs/ROADMAP.md) for the implementation plan and current
status.

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

Authorization, revocation, onboarding, JSON-RPC commands, and experimental
Home Assistant packaging are implemented. See [the roadmap](docs/ROADMAP.md)
for the current milestone and the known limitation around live
credential-possession proofs.

## Getting started (dev)

See [the roadmap](docs/ROADMAP.md) for milestones and the
[gateway guide](docs/GATEWAY.md) for local development and owner commands.

## Home Assistant app (experimental)

Home Assistant OS and Supervised users can add this repository to the app
store:

```text
https://github.com/jacksonriding/ha-didcomm
```

Install **ha-didcomm**, select Supervisor-managed TLS certificate files, set
`public_endpoint` to the matching HTTPS URL on port 8000, and start the app.
The app bundles ACA-Py, a TLS proxy, and the gateway, stores identity data
under the Supervisor-managed `/data` volume, and uses the Home Assistant API
proxy with `SUPERVISOR_TOKEN`. It does not require a long-lived Home Assistant
token. See [gateway/DOCS.md](gateway/DOCS.md) for configuration and security
notes.

Home Assistant Container users can instead use
[compose.standalone.yml](compose.standalone.yml); see
[standalone guide](docs/STANDALONE.md) for setup, persistence, and owner
commands.

## Repository layout

```text
docs/                    Project, gateway, and deployment documentation
custom_components/       Home Assistant custom integration
gateway/config.yaml      Home Assistant app metadata
gateway/src/ha_didcomm/  Python gateway package
gateway/tests/           Automated gateway tests
compose.yml              Local two-agent development stack
compose.standalone.yml   Standalone deployment stack
```

To show DIDComm connections and credentials in Home Assistant's UI, install
the [custom integration](docs/HOME_ASSISTANT_INTEGRATION.md).

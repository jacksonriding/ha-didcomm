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
2. Requires a fresh credential-possession proof and checks active local grants
3. Translates authorized commands into Home Assistant REST API calls

## Status

Authorization, revocation, onboarding, JSON-RPC commands, and experimental
Home Assistant packaging and per-command proof are implemented. Docker
Container smoke passed for DID exchange, credential issuance, a fresh signed
proof before an allowed HA call, and denial of disallowed, revoked, and
missing-wallet-VC commands, with exact-fingerprint selection enabled. The full
standalone lifecycle, app `0.0.12` Docker rebuild, and version/Compose checks
also passed. Physical HA OS validation has not been performed. See
[the roadmap](docs/ROADMAP.md) for remaining validation and release status.

The per-command authorization flow requires a fresh ACA-Py Present Proof 2.0
(PP2) DIF presentation using `Ed25519Signature2018` and a home/command-bound
random challenge. The signed challenge incorporates a hash of `HOME_ID`, the
home issuer, the command fingerprint, and a fresh random 256-bit nonce.
ACA-Py drops `domain` during signing, so the request omits the optional domain;
authorization does not rely on a signed or checked `proof.domain`.
The gateway retrieves the authoritative proof record
from ACA-Py's private Admin API and requires it to be verified and bound to
the same connection and pending request. The presentation's signing
verification method must belong to the credential's `did:key` subject, and
the presented credential must match an exact active local grant, including
expiry and revocation checks before dispatch.

Persistent replay suppression retains typed JSON-RPC IDs for 24 hours; the
gateway never retries Home Assistant dispatch after a crash. This does not
add service/action permissions. The [reference controller](docs/CONTROLLER.md)
explicitly selects the holder with `dif.issuer_id` and waits up to 45 seconds;
the default proof timeout is 30 seconds. Other wallets must respond to PP2
requests. The selected deployment pin is the official ACA-Py `py3.13-1.6.2rc0`
image containing PR #4217; the stable rolling tag still serves the old July 28
registry image. See the [exact digest and rebuild instructions](docs/GATEWAY.md#aca-py-deployment-pin-coordinator)
for every Compose deployment and the bundled app. Upgrade both the home and
controller, preserving wallet volumes, keys, and existing credentials. The pin
is applied in all three Compose files and the app Dockerfile.

This is experimental software, not a production security boundary. In
particular, do not rely on it as the only protection for locks, alarms, garage
doors, or other safety-critical devices. See [SECURITY.md](SECURITY.md) before
deploying it.

## Getting started (dev)

See [the roadmap](docs/ROADMAP.md) for milestones and the
[gateway guide](docs/GATEWAY.md) for local development and owner commands.

For a contributor environment and the checks run in continuous integration,
see [CONTRIBUTING.md](CONTRIBUTING.md).

## Home Assistant app (experimental)

Home Assistant OS and Supervised users can add this repository to the app
store:

```text
https://github.com/jacksonriding/ha-didcomm
```

Install **ha-didcomm**, select Supervisor-managed TLS certificate files, set
`public_endpoint` to the matching HTTPS URL on port 8000, and start the app.
Generate and configure a separate `owner_api_token` to enable the custom
integration's administrator-only onboarding and revocation actions.
The app bundles ACA-Py, a TLS proxy, and the gateway, stores identity data
under the Supervisor-managed `/data` volume, and uses the Home Assistant API
proxy with `SUPERVISOR_TOKEN`. It does not require a long-lived Home Assistant
token. See [gateway/DOCS.md](gateway/DOCS.md) for configuration and security
notes.

Home Assistant Container users can instead use
[compose.standalone.yml](compose.standalone.yml); see
[standalone guide](docs/STANDALONE.md) for setup, persistence, and owner
commands.

To exercise the guest side from another computer or Raspberry Pi, use the
[reference remote controller](docs/CONTROLLER.md). It provides a persistent
ACA-Py identity and simple commands for accepting an invitation and calling an
authorized Home Assistant service.

## Repository layout

```text
docs/                    Project, gateway, and deployment documentation
custom_components/       Home Assistant custom integration
gateway/config.yaml      Home Assistant app metadata
gateway/src/ha_didcomm/  Python gateway package
gateway/tests/           Automated gateway tests
compose.yml              Local two-agent development stack
compose.standalone.yml   Standalone deployment stack
compose.controller.yml   Reference remote-controller stack
```

To show DIDComm connections and credentials in Home Assistant's UI, install
the [custom integration](docs/HOME_ASSISTANT_INTEGRATION.md).
Multiple independently operated gateways can be added to the same Home
Assistant instance; see the [multi-home guide](docs/MULTI_HOME.md).

## Open source

ha-didcomm is licensed under the [Apache License 2.0](LICENSE). Contributions
are welcome; please read the [contribution guide](CONTRIBUTING.md),
[code of conduct](CODE_OF_CONDUCT.md), and [security policy](SECURITY.md).

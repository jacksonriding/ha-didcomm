# Reference remote controller

The reference controller completes the guest side of the alpha workflow. It
runs a persistent ACA-Py wallet, accepts an invitation URL, receives access
credentials automatically, sends JSON-RPC commands, answers the gateway's
per-command proof request, and waits for its structured reply. Run it on a
different computer or Raspberry Pi
from the Home Assistant gateway to model a real guest.

This is a command-line reference client, not a mobile wallet. It is intended
to make the complete flow reproducible while wallet interoperability is still
experimental.

The implemented controller flow has passing Docker Container smoke coverage
for credential issuance, proof-required allowed calls, and denial of
disallowed, revoked, and missing-wallet-VC commands with exact-fingerprint
selection enabled. See the
[roadmap](ROADMAP.md) for remaining validation; physical HA OS remains
unvalidated. Both sides must use the
selected official ACA-Py `py3.13-1.6.2rc0` image pinned by digest. This release
candidate contains PR #4217; the stable rolling `py3.13-1.6-lts` registry tag
still serves the old July 28 image after pulling. Follow the
[exact pin and home/controller rebuild instructions](GATEWAY.md#aca-py-deployment-pin-coordinator),
preserving wallet volumes, keys, existing credentials, and local grants.
Upgrade both the home and controller; upgrading only the home leaves the old
controller without the required per-command proof response flow. Existing
credentials are retained and do not need to be reissued for this upgrade.

## Start the controller

On the controller computer, clone this repository and create its environment
file:

```powershell
Copy-Item .env.controller.example .env.controller
python -c "import secrets; print(secrets.token_hex(32))"
python -c "import secrets; print(secrets.token_hex(32))"
```

Put the generated secrets in `CONTROLLER_WALLET_KEY` and
`CONTROLLER_ADMIN_API_KEY`. The wallet key is passed to ACA-Py as a single
argument, so an existing strong value that starts with `-` is also safe. Set
`CONTROLLER_PUBLIC_ENDPOINT` to an address the
home gateway can reach, normally the controller computer's fixed LAN address:

```text
CONTROLLER_PUBLIC_ENDPOINT=http://192.168.1.20:8010
```

Then build the controller CLI and inbox, and start the persistent agent and
reply inbox:

```powershell
docker compose --env-file .env.controller -f compose.controller.yml build
docker compose --env-file .env.controller -f compose.controller.yml up -d controller-agent controller-inbox
```

The published port is only the DIDComm listener. The ACA-Py Admin API and the
reply inbox remain private inside the Compose network. DIDComm message bodies
are encrypted, but plain HTTP still exposes transport metadata and provides no
server authentication. Use this HTTP example only on a trusted LAN. Put the
listener behind trusted HTTPS before routing it over the internet.

Show or create the controller's stable credential-holder DID:

```powershell
docker compose --env-file .env.controller -f compose.controller.yml run --rm controller identity
```

Keep the printed `did:key` value for the issuance step. Re-running the command
returns the same identity. The selection is saved in the `controller-data`
SQLite store and is checked against the persistent wallet every time. An empty
wallet creates and saves one DID; a wallet with one existing DID adopts it.
The command fails closed if a saved DID is missing or an unconfigured wallet
contains multiple `did:key` identities.

During an intentional recovery, select one DID that already exists in the
wallet and persist that choice with either:

```powershell
docker compose --env-file .env.controller -f compose.controller.yml run --rm controller identity --did "did:key:..."
```

or `CONTROLLER_HOLDER_DID=did:key:...` in `.env.controller`. A selector never
creates the requested DID. Remove the environment selector after the choice is
saved so subsequent wallet drift is detected.

## Connect and receive access

On the home gateway, create a single-use invitation:

```powershell
docker compose --env-file .env.standalone -f compose.standalone.yml run --rm gateway python -m ha_didcomm.cli invite --label "My home"
```

On the controller computer, the safest route is to save either the raw
invitation URL, JSON response, or copied Home Assistant action response in a
private temporary file and pipe it over standard input. This keeps the
single-use invitation out of the process argument list:

```powershell
Get-Content -Raw .\invitation.txt | docker compose --env-file .env.controller -f compose.controller.yml run --rm -T controller connect --stdin
Remove-Item .\invitation.txt
```

The original quoted positional form remains available for compatibility:

```powershell
docker compose --env-file .env.controller -f compose.controller.yml run --rm controller connect "<invitation_url>"
```

Input must contain exactly one valid `oob` or `_oob` invitation. Ambiguous or
malformed input is rejected without printing its contents.

After a few seconds, list connections on both machines. Connection IDs are
pairwise records, so the home-side and controller-side IDs are deliberately
different.

Home gateway:

```powershell
docker compose --env-file .env.standalone -f compose.standalone.yml run --rm gateway python -m ha_didcomm.cli connections
```

Controller:

```powershell
docker compose --env-file .env.controller -f compose.controller.yml run --rm controller connections
```

On the home gateway, issue access using the **home-side connection ID** and
the controller's `did:key`. Repeat `--permission` for each entity or pattern:

```powershell
$expires = (Get-Date).ToUniversalTime().AddHours(8).ToString("yyyy-MM-ddTHH:mm:ssZ")
docker compose --env-file .env.standalone -f compose.standalone.yml run --rm gateway python -m ha_didcomm.cli issue `
  <home_connection_id> <controller_did_key> `
  --role guest `
  --permission "light.guest_room" `
  --expires $expires
```

## Send a command

Use the **controller-side connection ID** when sending a command:

```powershell
docker compose --env-file .env.controller -f compose.controller.yml run --rm controller call `
  <controller_connection_id> turn_on light.guest_room
```

For the pending command, the reference controller answers the gateway's
Present Proof 2.0 (PP2) DIF request and explicitly sends
`dif.issuer_id` set to its selected holder `did:key` when submitting the
presentation to ACA-Py. This selects the presentation signer; it is the
holder's DID, not the home's credential-issuer DID. The presentation uses
`Ed25519Signature2018` and the request's exact home/command-bound random
challenge, which incorporates a hash of `HOME_ID`, the home issuer, the command
fingerprint, and a fresh random 256-bit nonce. ACA-Py drops `domain` during
signing, so requests omit that optional field; there is no reliance on a
signed or checked `proof.domain`. The signing verification method must belong
to the VC's `did:key` subject.

The request's input descriptor ID is opaque and dynamic, carrying exact
eligible VC fingerprints. The controller explicitly submits `record_ids`
keyed by that descriptor ID to select the eligible wallet credential; it must
not hardcode the descriptor ID or rely on wallet ordering. This fixes selection
of a revoked grant ahead of an active one issued in the same second.

The gateway retrieves the authoritative private Admin API record and requires
verification for the same connection and pending request. It also requires an
exact active local grant and rechecks expiry and revocation before HA dispatch.
Sending a Basic Message alone is insufficient. Other wallets must implement
the PP2 DIF response flow. The development `acapy-user` agent already has
`--auto-respond-presentation-request` enabled. The reference controller uses
its explicit response flow with the selected holder; keep the `controller
call` process running while it handles the pending command and proof exchange.

The expected successful reply is:

```json
{
  "id": "...",
  "jsonrpc": "2.0",
  "result": {
    "executed": true
  }
}
```

An authorization denial prints JSON-RPC error `-32001` and exits with status
2. The default proof timeout is 30 seconds. A missing controller reply exits
after 45 seconds, allowing time for the proof exchange and response; inspect `docker compose logs
controller-agent controller-inbox` on the controller and the gateway logs on
the home machine.

Use a fresh JSON-RPC ID for each new command. The gateway persistently
suppresses repeated typed IDs on the same connection for 24 hours, treating
numeric and string IDs as distinct. It never retries HA dispatch after a
crash. A missing reply does not establish that HA did nothing; inspect the
entity state before issuing another command with a new ID.

To remove access, use the home gateway's `revoke-credential` or
`revoke-connection` owner command. The next controller call will be denied.

## Persistence and removal

The `controller-wallet` volume contains the controller's keys, connections,
and received credentials. The `controller-data` volume contains command
replies and the selected holder DID. Back up both volumes together if this
identity matters. Do not run `docker compose down --volumes` unless you intend
to delete them.

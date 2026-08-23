# Reference remote controller

The reference controller completes the guest side of the alpha workflow. It
runs a persistent ACA-Py wallet, accepts an invitation URL, receives access
credentials automatically, sends JSON-RPC commands, and waits for the
gateway's structured reply. Run it on a different computer or Raspberry Pi
from the Home Assistant gateway to model a real guest.

This is a command-line reference client, not a mobile wallet. It is intended
to make the complete flow reproducible while wallet interoperability is still
experimental.

## Start the controller

On the controller computer, clone this repository and create its environment
file:

```powershell
Copy-Item .env.controller.example .env.controller
python -c "import secrets; print(secrets.token_urlsafe(32))"
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

Put the generated secrets in `CONTROLLER_WALLET_KEY` and
`CONTROLLER_ADMIN_API_KEY`. Set `CONTROLLER_PUBLIC_ENDPOINT` to an address the
home gateway can reach, normally the controller computer's fixed LAN address:

```text
CONTROLLER_PUBLIC_ENDPOINT=http://192.168.1.20:8010
```

Then start the persistent agent and reply inbox:

```powershell
docker compose --env-file .env.controller -f compose.controller.yml up -d --build controller-agent controller-inbox
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
returns the same identity from the persistent wallet.

## Connect and receive access

On the home gateway, create a single-use invitation:

```powershell
docker compose --env-file .env.standalone -f compose.standalone.yml run --rm gateway python -m ha_didcomm.cli invite --label "My home"
```

On the controller computer, pass the printed invitation URL as one quoted
argument:

```powershell
docker compose --env-file .env.controller -f compose.controller.yml run --rm controller connect "<invitation_url>"
```

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

A successful round trip prints:

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
2. A missing reply exits after 15 seconds; inspect `docker compose logs
controller-agent controller-inbox` on the controller and the gateway logs on
the home machine.

To remove access, use the home gateway's `revoke-credential` or
`revoke-connection` owner command. The next controller call will be denied.

## Persistence and removal

The `controller-wallet` volume contains the controller's keys, connections,
and received credentials. The `controller-data` volume contains command
replies. Back up the wallet volume if this identity matters. Do not run
`docker compose down --volumes` unless you intend to delete it.

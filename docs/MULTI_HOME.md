# Multi-home delegated access

Each home runs its own ha-didcomm gateway, ACA-Py wallet, issuer DID, and
credential database. A guest may reuse one stable subject `did:key` across
homes, but establishes a separate pairwise DIDComm connection with each home.

```text
                         guest did:key
                         /           \
              DIDComm connection   DIDComm connection
                      /                 \
             Home A gateway       Home B gateway
             issuer A, home-a     issuer B, home-b
```

The credentials remain independent:

- Home A might grant `light.guest_room` until Friday.
- Home B might grant `lock.front_door` for one afternoon.
- A credential is accepted only when both its `credentialSubject.home` and
  `issuer` match the gateway processing the command.
- Revoking the guest at one home does not affect credentials issued by another
  home.

This design does not require homes to share wallets, databases, Admin APIs, or
Home Assistant tokens.

## Configure each home

Install a separate app or standalone deployment at each home. Give each one a
stable, unique `home_id`, its own HTTPS `public_endpoint`, and its own issuer
DID. Never copy ACA-Py or gateway data volumes between homes.

For each home:

1. Generate an invitation with a label that clearly identifies the home.
2. Have the guest accept it in their Aries-compatible agent.
3. List connections and select that home's connection to the guest.
4. Issue a credential using the guest's stable subject DID and permissions for
   entities belonging only to that home.

Using the gateway CLI, the owner-side commands are:

```powershell
python -m ha_didcomm.cli invite --label "Beach house"
python -m ha_didcomm.cli connections
python -m ha_didcomm.cli issue <connection_id> <guest_subject_did> `
  --role visitor `
  --permission "lock.front_door" `
  --expires "2026-08-20T08:00:00Z"
```

Run those commands inside the relevant app or Compose deployment as described
in the deployment guide. Repeat them independently at the other home; do not
reuse a connection ID or credential exchange ID between gateways.

## Display multiple homes in Home Assistant

The custom integration accepts multiple config entries. Add it once for each
gateway's HTTPS status URL. The gateway issuer DID namespaces entity unique IDs,
and the config entry title uses the gateway's `home_id`, so connections and
credentials from different homes remain distinct.

The integration remains read-only. Invitations, issuance, and revocation are
currently owner CLI operations.

## Security boundary

Multi-home support does not federate trust between homes. Every gateway makes
its own authorization decision from its own issuer-scoped records. Live
credential-possession proof is still deferred as documented in the roadmap;
the current check remains bound to the pairwise connection on which that home
issued the credential.

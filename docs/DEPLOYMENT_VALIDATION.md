# Deployment lifecycle validation

This checklist verifies that upgrades and backups preserve the gateway's
identity and authorization state. Use a non-critical test home and a test
credential; this project is still experimental.

## Automated standalone validation

From a clean checkout with Docker and OpenSSL installed:

```bash
python3 scripts/docker_lifecycle_test.py
```

The test creates unique project and volume names and then:

1. starts a fresh standalone installation with a temporary TLS certificate;
2. creates and records a home issuer DID and test credential;
3. force-replaces the ACA-Py, gateway, and TLS containers;
4. checks that the issuer DID, gateway instance ID, and credential survive;
5. stops the stateful services and archives both named volumes;
6. deletes the deployment and its volumes, recreates empty volumes, and
   restores the archives;
7. starts the restored deployment and revokes the restored credential through
   the authenticated owner API; and
8. removes the isolated project and volumes.

Failure logs are printed before the isolated project is removed. Never point
this test at an existing Compose project: its volume-loss stage is
intentionally destructive.

## Home Assistant OS checklist

Home Assistant OS and Supervisor backup behavior must be checked on a real test
installation. Record the Home Assistant version, app version, architecture,
and date alongside the result.

### Fresh installation

- Add this repository to the app store and install `ha-didcomm`.
- Configure valid certificate files, an HTTPS public endpoint, a unique home
  ID, and a random owner token of at least 32 characters.
- Start the app and confirm its log contains no repeated restarts or missing
  certificate errors.
- Request `/health`, configure the custom integration with the same public URL
  and owner token, and create a single-use invitation through
  `ha_didcomm.create_invitation`.
- Connect a test controller, issue a short-lived test credential, and record
  the `/status` `instance_id`, connection ID, credential exchange ID, state,
  permissions, and expiry.

### Upgrade

- Create a Home Assistant backup before installing the candidate app version.
- Install the candidate version without uninstalling the existing app or
  deleting its data.
- Confirm the app starts and `/status` retains the recorded `instance_id`,
  connection, and credential metadata.
- Confirm the existing owner token still authenticates and exercise a harmless
  permitted entity through the test controller.

### Backup and restore

- Stop activity from the test controller and create a backup containing the
  `ha-didcomm` app. The app declares `backup: cold`, so Supervisor must stop it
  while `/data` is captured.
- Restore that backup on the test installation, including the app and its
  configuration. Ensure the referenced TLS certificate files are also present
  in `/ssl`.
- Start the restored app and confirm `/status` retains the exact issuer-backed
  `instance_id`, connection ID, credential exchange ID, permission list,
  expiry, and state.
- Revoke the restored test credential through Home Assistant and confirm its
  sensor changes to `revoked` and the controller is denied immediately.
- Restart Home Assistant once more and confirm the revoked state persists.

## Evidence record

Copy this table into the release issue or test notes. Do not record tokens,
wallet keys, invitations, certificates, or full DIDs.

| Field | Result |
| --- | --- |
| Date | |
| Tester | |
| Deployment | Home Assistant OS / standalone Container |
| Home Assistant version | |
| ha-didcomm app version | |
| Integration version | |
| Architecture | |
| Fresh install | Pass / Fail |
| Upgrade | Pass / Fail |
| Backup and restore | Pass / Fail |
| Identity preserved | Pass / Fail |
| Authorization and revocation preserved | Pass / Fail |
| Notes or issue links | |

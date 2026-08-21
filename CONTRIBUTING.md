# Contributing to ha-didcomm

Thank you for helping make delegated Home Assistant access safer and easier to
use. Bug reports, documentation fixes, interoperability results, threat-model
feedback, and code contributions are welcome.

The project is experimental. Do not test changes against locks, alarms,
garage doors, or other safety-critical entities unless you understand and
accept the risk.

## Before opening a change

- Search existing issues and pull requests.
- Open an issue before making a large architectural or protocol change.
- Never include Home Assistant tokens, wallet keys, credentials, invitations,
  private DIDs, certificates, or a populated SQLite store in an issue or commit.
- Keep changes within the gateway boundary described in
  [the roadmap](docs/ROADMAP.md).

## Development setup

Prerequisites are Python 3.12 or 3.13 and Docker with Docker Compose.

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r gateway/requirements-dev.txt
```

On macOS or Linux, activate the environment with
`source .venv/bin/activate` instead.

Run the same checks used by continuous integration:

```powershell
python scripts/check_versions.py
python -m pytest
python -m compileall -q gateway/src custom_components
docker compose -f compose.yml config --quiet
docker compose --env-file .env.standalone.example `
  -f compose.standalone.yml config --quiet
```

The manual DIDComm and Home Assistant test is documented in
[docs/GATEWAY.md](docs/GATEWAY.md). Never use a production Home Assistant
token in the development stack.

## Pull requests

- Add or update tests for changed behavior.
- Update user documentation and the changelog when behavior changes.
- Keep pull requests focused and explain security consequences explicitly.
- Confirm that the commands above pass.
- Use clear commit messages; maintainers may squash commits when merging.

By contributing, you agree that your contribution is licensed under the
[Apache License 2.0](LICENSE).

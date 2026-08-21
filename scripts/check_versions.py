"""Validate release versions without requiring third-party packages."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import sys


ROOT = Path(__file__).resolve().parents[1]
SEMVER = re.compile(
    r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)"
    r"(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?$"
)


def _gateway_version() -> str:
    config = (ROOT / "gateway" / "config.yaml").read_text(encoding="utf-8")
    match = re.search(r'^version:\s*["\']?([^"\'\s]+)["\']?\s*$', config, re.MULTILINE)
    if not match:
        raise ValueError("gateway/config.yaml does not contain a version")
    return match.group(1)


def _integration_version() -> str:
    manifest_path = ROOT / "custom_components" / "ha_didcomm" / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    version = manifest.get("version")
    if not isinstance(version, str):
        raise ValueError(f"{manifest_path.relative_to(ROOT)} has no string version")
    return version


def _latest_changelog_version() -> str:
    changelog = (ROOT / "gateway" / "CHANGELOG.md").read_text(encoding="utf-8")
    match = re.search(r"^##\s+([^\s]+)\s*$", changelog, re.MULTILINE)
    if not match:
        raise ValueError("gateway/CHANGELOG.md has no release heading")
    return match.group(1)


def _release_tag(cli_tag: str | None) -> str | None:
    if cli_tag:
        return cli_tag
    if os.getenv("GITHUB_REF_TYPE") == "tag":
        return os.getenv("GITHUB_REF_NAME")
    return None


def check(tag: str | None = None) -> list[str]:
    errors: list[str] = []
    try:
        gateway = _gateway_version()
        integration = _integration_version()
        changelog = _latest_changelog_version()
    except (OSError, ValueError, json.JSONDecodeError) as error:
        return [str(error)]

    for label, version in (
        ("gateway", gateway),
        ("Home Assistant integration", integration),
    ):
        if not SEMVER.fullmatch(version):
            errors.append(f"{label} version is not semantic: {version!r}")

    if changelog != gateway:
        errors.append(
            "gateway/config.yaml version "
            f"{gateway!r} does not match the latest changelog entry {changelog!r}"
        )

    release_tag = _release_tag(tag)
    if release_tag and release_tag != f"v{gateway}":
        errors.append(
            f"release tag {release_tag!r} does not match gateway version v{gateway}"
        )

    if not errors:
        print(f"gateway={gateway}; integration={integration}")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--tag",
        help="optional release tag to compare with the gateway version",
    )
    args = parser.parse_args()
    errors = check(args.tag)
    for error in errors:
        print(f"error: {error}", file=sys.stderr)
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())

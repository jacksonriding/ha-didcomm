"""Owner-facing command line tools for gateway onboarding."""
import argparse
import asyncio
import sys
from collections.abc import Sequence

import httpx
import qrcode

import acapy
import credentials
import owner


def render_terminal_qr(data: str) -> str:
    """Render a QR code compactly using two vertical modules per character."""
    qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, border=4)
    qr.add_data(data)
    qr.make(fit=True)
    matrix = qr.get_matrix()

    lines = []
    for row_index in range(0, len(matrix), 2):
        top = matrix[row_index]
        bottom = matrix[row_index + 1] if row_index + 1 < len(matrix) else [False] * len(top)
        characters = []
        for top_pixel, bottom_pixel in zip(top, bottom):
            if top_pixel and bottom_pixel:
                characters.append("█")
            elif top_pixel:
                characters.append("▀")
            elif bottom_pixel:
                characters.append("▄")
            else:
                characters.append(" ")
        lines.append("".join(characters))
    return "\n".join(lines)


async def create_invitation(args: argparse.Namespace) -> str:
    result = await acapy.create_oob_invitation(
        label=args.label,
        multi_use=args.multi_use,
        auto_accept=not args.manual_accept,
    )
    return result["invitation_url"]


def print_connections(records: list[dict]) -> None:
    print("CONNECTION ID\tSTATE\tLABEL\tTHEIR DID")
    for record in records:
        values = (
            record.get("connection_id", "-"),
            record.get("rfc23_state") or record.get("state", "-"),
            record.get("their_label", "-"),
            record.get("their_did", "-"),
        )
        print("\t".join(str(value or "-") for value in values))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Manage ha-didcomm onboarding")
    commands = parser.add_subparsers(dest="command", required=True)
    invite = commands.add_parser("invite", help="create and display an OOB invitation")
    invite.add_argument("--label", help="label shown to the invited agent")
    invite.add_argument(
        "--multi-use",
        action="store_true",
        help="allow more than one agent to use this invitation",
    )
    invite.add_argument(
        "--manual-accept",
        action="store_true",
        help="require the home agent to accept the connection request manually",
    )
    commands.add_parser("connections", help="list agents connected to the home")

    issue = commands.add_parser("issue", help="issue a scoped access credential")
    issue.add_argument("connection_id")
    issue.add_argument("subject_did")
    issue.add_argument(
        "--permission",
        action="append",
        required=True,
        dest="permissions",
        help="allowed entity pattern; repeat for multiple patterns",
    )
    issue.add_argument("--role", default="guest")
    issue.add_argument("--expires", help="ISO 8601 expiration timestamp")

    revoke_credential = commands.add_parser(
        "revoke-credential", help="revoke one issued credential"
    )
    revoke_credential.add_argument("credential_exchange_id")
    revoke_connection = commands.add_parser(
        "revoke-connection", help="revoke every credential for a connection"
    )
    revoke_connection.add_argument("connection_id")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "invite":
        try:
            invitation_url = asyncio.run(create_invitation(args))
        except (httpx.HTTPError, ValueError) as error:
            parser.exit(1, f"error: could not create invitation: {error}\n")
        print("Scan this invitation with an Aries-compatible agent:\n")
        print(render_terminal_qr(invitation_url))
        print(f"\nInvitation URL:\n{invitation_url}")
    elif args.command == "connections":
        try:
            records = asyncio.run(acapy.list_connections())
        except (httpx.HTTPError, ValueError) as error:
            parser.exit(1, f"error: could not list connections: {error}\n")
        print_connections(records)
    elif args.command == "issue":
        try:
            credential_exchange_id = asyncio.run(
                owner.issue_access_credential(
                    connection_id=args.connection_id,
                    subject_did=args.subject_did,
                    role=args.role,
                    permissions=args.permissions,
                    expires=args.expires,
                )
            )
        except (httpx.HTTPError, ValueError) as error:
            parser.exit(1, f"error: could not issue credential: {error}\n")
        print(f"Issued credential: {credential_exchange_id}")
    elif args.command == "revoke-credential":
        if not credentials.revoke_credential(args.credential_exchange_id):
            parser.exit(1, "error: credential not found\n")
        print(f"Revoked credential: {args.credential_exchange_id}")
    elif args.command == "revoke-connection":
        if not credentials.revoke_connection(args.connection_id):
            parser.exit(1, "error: connection credentials not found\n")
        print(f"Revoked all credentials for connection: {args.connection_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

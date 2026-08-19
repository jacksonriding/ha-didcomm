"""Owner-facing command line tools for gateway onboarding."""
import argparse
import asyncio
import sys
from collections.abc import Sequence

import httpx
import qrcode

import acapy


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
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

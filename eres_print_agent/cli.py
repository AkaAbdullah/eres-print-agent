"""`eres-print-agent` command-line entry point.

Per spec section 2/7: this CLI is for installation, diagnostics, pairing,
and troubleshooting — administrators/developers, not end users. Normal
operation requires no commands at all once paired; the service just runs.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import tempfile
from pathlib import Path

from . import __version__
from .config import load_config
from .credentials import delete_agent_secret, load_agent_secret
from .diagnostics import collect_printers, collect_status, format_printers_text, format_status_text, tail_log_lines
from .logging_setup import configure_logging


def _require_windows(command: str) -> None:
    if sys.platform != "win32":
        print(f"`{command}` is only available on Windows (this manages the Windows Service).", file=sys.stderr)
        sys.exit(1)


def _print_json(data) -> None:
    print(json.dumps(data, indent=2, default=str))


def cmd_version(_args: argparse.Namespace) -> int:
    print(f"eres-print-agent {__version__}")
    return 0


def cmd_pair(args: argparse.Namespace) -> int:
    from .core.pairing import pair

    web_url = args.web_url or "https://app.eres.cloud"
    result = asyncio.run(pair(web_url=web_url, code=args.code))

    if not result.success:
        print(f"Pairing failed: {result.error}", file=sys.stderr)
        return 1

    print(f"Paired as agent {result.agent_id}.")

    if sys.platform != "win32":
        print("Run `eres-print-agent run` to run it in the foreground.")
        return 0

    # The installer already registered the service, and SvcDoRun reads the
    # config once at startup — so what it needs now is a restart to pick up
    # the credentials pairing just wrote, not a fresh `install`.
    from .service.windows_service import service_exists

    if service_exists():
        print("Almost done — restart the service so it picks up these credentials.")
        print("In an Administrator Command Prompt, run:")
        print("  eres-print-agent restart")
    else:
        print("The background service isn't installed yet.")
        print("In an Administrator Command Prompt, run:")
        print("  eres-print-agent install")
    return 0


def cmd_run(_args: argparse.Namespace) -> int:
    """Foreground run — used for local/dev/non-Windows deployment, and by
    the Windows service wrapper's own internal call into core.agent.Agent
    (not this CLI command directly, but the same code path)."""
    config = load_config()
    if not config.is_paired:
        print("Not paired. Run `eres-print-agent pair <code>` first.", file=sys.stderr)
        return 1

    agent_secret = load_agent_secret(config.agentId)
    if not agent_secret:
        print("Paired, but no credential found in the OS keyring. Re-run `pair`.", file=sys.stderr)
        return 1

    configure_logging(config.logLevel)

    async def _main() -> None:
        # Agent()/WsClient() create asyncio.Event()s in __init__, which must
        # happen while this coroutine's event loop is the running loop — an
        # Event created before asyncio.run() starts binds to the wrong loop
        # and raises "attached to a different loop" the first time it's
        # awaited.
        from .core.agent import Agent

        agent = Agent(config, agent_secret)
        try:
            await agent.run()
        except asyncio.CancelledError:
            agent.stop()
            raise

    try:
        asyncio.run(_main())
    except KeyboardInterrupt:
        pass
    return 0


def cmd_install(_args: argparse.Namespace) -> int:
    _require_windows("install")
    from .service.windows_service import install_service

    install_service()
    print("ERES Print Agent service installed and set to start automatically.")

    config = load_config()
    if not config.is_paired:
        print("Not paired yet — run `eres-print-agent pair <code>` from ERES Settings > Printers,")
        print("then `eres-print-agent start`.")
    return 0


def cmd_uninstall(_args: argparse.Namespace) -> int:
    _require_windows("uninstall")
    from .service.windows_service import uninstall_service

    uninstall_service()
    config = load_config()
    if config.agentId:
        delete_agent_secret(config.agentId)
    print("ERES Print Agent service removed.")
    return 0


def cmd_start(_args: argparse.Namespace) -> int:
    _require_windows("start")
    from .service.windows_service import start_service

    start_service()
    print("ERES Print Agent service started.")
    return 0


def cmd_stop(_args: argparse.Namespace) -> int:
    _require_windows("stop")
    from .service.windows_service import stop_service

    stop_service()
    print("ERES Print Agent service stopped.")
    return 0


def cmd_restart(_args: argparse.Namespace) -> int:
    _require_windows("restart")
    from .service.windows_service import restart_service

    restart_service()
    print("ERES Print Agent service restarted.")
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    status = collect_status()
    if args.json:
        _print_json(status)
    else:
        print(format_status_text(status))
    return 0


def cmd_printers(args: argparse.Namespace) -> int:
    printers = collect_printers()
    if args.json:
        _print_json(printers)
    else:
        print(format_printers_text(printers))
    return 0


def cmd_logs(args: argparse.Namespace) -> int:
    print(tail_log_lines(args.lines))
    return 0


def _build_local_test_pdf(path: Path) -> None:
    """A tiny, self-contained PDF for `test-print` — this command is meant
    to work without any connection to ERES, so it can't reuse a
    server-generated document."""
    text = "ERES Print Agent - Local Test Page"
    content = f"BT /F1 18 Tf 40 750 Td ({text}) Tj ET"
    objects = [
        "1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj",
        "2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj",
        "3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 612 792]/Contents 4 0 R/Resources<</Font<</F1 5 0 R>>>>>>endobj",
        f"4 0 obj<</Length {len(content)}>>stream\n{content}\nendstream endobj",
        "5 0 obj<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>endobj",
    ]
    body = "%PDF-1.4\n"
    offsets = []
    for obj in objects:
        offsets.append(len(body.encode("latin1")))
        body += obj + "\n"
    xref_start = len(body.encode("latin1"))
    body += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n"
    for offset in offsets:
        body += f"{offset:010d} 00000 n \n"
    body += f"trailer<</Size {len(objects) + 1}/Root 1 0 R>>\nstartxref\n{xref_start}\n%%EOF"
    path.write_bytes(body.encode("latin1"))


def cmd_test_print(args: argparse.Namespace) -> int:
    from .printing.factory import build_printer_manager

    printer_manager = build_printer_manager()
    discovered = printer_manager.discover()
    if not discovered:
        print("No printers discovered.", file=sys.stderr)
        return 1

    target = args.printer
    if target:
        match = next((p for p in discovered if p.local_printer_id == target), None)
        if not match:
            print(f"Printer {target!r} not found. Known printers:", file=sys.stderr)
            for p in discovered:
                print(f"  - {p.local_printer_id}", file=sys.stderr)
            return 1
    else:
        match = next((p for p in discovered if p.is_default), discovered[0])

    with tempfile.TemporaryDirectory() as tmp_dir:
        pdf_path = Path(tmp_dir) / "eres-print-agent-test.pdf"
        _build_local_test_pdf(pdf_path)
        try:
            printer_manager.print(match.local_printer_id, str(pdf_path), 1)
        except Exception as error:
            print(f"Test print failed: {error}", file=sys.stderr)
            return 1

    print(f"Test print sent to {match.display_name}.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="eres-print-agent", description="ERES Print Agent")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("version").set_defaults(func=cmd_version)

    pair_parser = subparsers.add_parser("pair", help="Redeem a pairing code from ERES Settings > Printers")
    pair_parser.add_argument("code")
    pair_parser.add_argument("--web-url", dest="web_url", default=None, help="ERES app URL (default: https://app.eres.cloud)")
    pair_parser.set_defaults(func=cmd_pair)

    subparsers.add_parser("run", help="Run in the foreground (dev/non-Windows)").set_defaults(func=cmd_run)

    subparsers.add_parser("install", help="Install and start the Windows service").set_defaults(func=cmd_install)
    subparsers.add_parser("uninstall", help="Remove the Windows service").set_defaults(func=cmd_uninstall)
    subparsers.add_parser("start", help="Start the Windows service").set_defaults(func=cmd_start)
    subparsers.add_parser("stop", help="Stop the Windows service").set_defaults(func=cmd_stop)
    subparsers.add_parser("restart", help="Restart the Windows service").set_defaults(func=cmd_restart)

    status_parser = subparsers.add_parser("status", help="Show agent status")
    status_parser.add_argument("--json", action="store_true")
    status_parser.set_defaults(func=cmd_status)

    printers_parser = subparsers.add_parser("printers", help="List discovered printers")
    printers_parser.add_argument("--json", action="store_true")
    printers_parser.set_defaults(func=cmd_printers)

    logs_parser = subparsers.add_parser("logs", help="Show recent log lines")
    logs_parser.add_argument("--lines", type=int, default=200)
    logs_parser.set_defaults(func=cmd_logs)

    test_print_parser = subparsers.add_parser("test-print", help="Print a local test page (bypasses ERES)")
    test_print_parser.add_argument("--printer", default=None, help="Local printer name (default: OS default printer)")
    test_print_parser.set_defaults(func=cmd_test_print)

    return parser


# These five talk to the Service Control Manager, which refuses a
# non-elevated caller. Everything else (pair, status, printers, logs) is
# fine as a normal user.
_SERVICE_COMMANDS = frozenset({"install", "uninstall", "start", "stop", "restart"})
_ERROR_ACCESS_DENIED = 5


def _looks_like_scm_launch(argv) -> bool:
    """The SCM starts a frozen service by running its exe with no arguments."""
    return (
        argv is None
        and sys.platform == "win32"
        and getattr(sys, "frozen", False)
        and len(sys.argv) == 1
    )


def main(argv=None) -> int:
    # Before argparse: a no-argument frozen launch is how the SCM starts the
    # service, and argparse would exit(2) on the missing subcommand without
    # ever answering the SCM, which then times out with error 1053.
    if _looks_like_scm_launch(argv):
        from .service.windows_service import run_service_dispatcher

        if run_service_dispatcher():
            return 0
        # Not actually started by the SCM — fall through and show usage.

    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except Exception as exc:
        # Without this the operator gets a raw pywin32 traceback
        # ("pywintypes.error: (5, 'OpenSCManager', 'Access is denied.')")
        # that doesn't say the one thing they need to do.
        if args.command not in _SERVICE_COMMANDS or getattr(exc, "winerror", None) != _ERROR_ACCESS_DENIED:
            raise
        print(
            f"Access denied. `eres-print-agent {args.command}` manages a Windows service,\n"
            "which needs an elevated prompt: right-click Command Prompt, choose\n"
            '"Run as administrator", then run the command again.',
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    sys.exit(main())

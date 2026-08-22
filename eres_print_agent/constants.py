"""Shared constants for the ERES Print Agent.

Kept in one place so cli.py's human-readable output, the protocol codec,
and the state machine all agree on the same vocabulary as print-hub's
PROTOCOL.md and web/'s lib/print-agent/constants.ts.
"""

SERVICE_NAME = "ERESPrintAgent"
SERVICE_DISPLAY_NAME = "ERES Print Agent"
SERVICE_DESCRIPTION = (
    "Connects local printers to ERES. Discovers printers, receives print "
    "jobs, and reports status back to ERES. Managed from ERES Settings > "
    "Printers — see https://eres.cloud."
)

APP_VENDOR = "ERES"
APP_NAME = "PrintAgent"
KEYRING_SERVICE_NAME = "ERES Print Agent"

# Reconnect backoff schedule (seconds), per spec section 14. Resets to the
# first value after any successful connection.
RECONNECT_BACKOFF_SCHEDULE = [1, 2, 5, 10, 30, 60]

HEARTBEAT_INTERVAL_SECONDS = 30
PRINTER_SYNC_INTERVAL_SECONDS = 5 * 60

DOWNLOAD_MAX_BYTES = 25 * 1024 * 1024  # 25 MB — generous for a PDF, small enough to bound memory
DOWNLOAD_TIMEOUT_SECONDS = 30

PRINT_JOB_ERROR_CODES = frozenset(
    {
        "PRINTER_OFFLINE",
        "PRINTER_ERROR",
        "DOWNLOAD_FAILED",
        "CHECKSUM_MISMATCH",
        "TIMEOUT",
        "AGENT_RESTARTED_DURING_PRINT",
        "CANCELLED_BY_USER",
        "INVALID_JOB",
    }
)

PROTOCOL_VERSION = 1

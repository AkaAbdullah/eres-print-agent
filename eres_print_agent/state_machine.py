"""Print job status enum + legal-transition table.

Mirrors web/'s app/api/print-agent/hub/job-status/route.ts exactly — both
sides must agree on what's a valid transition, since web/ is the
authoritative record and will reject anything illegal.
"""

from __future__ import annotations

from enum import Enum


class PrintJobStatus(str, Enum):
    QUEUED = "QUEUED"
    RECEIVED = "RECEIVED"
    PRINTING = "PRINTING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    WAITING_FOR_PRINTER = "WAITING_FOR_PRINTER"


LEGAL_TRANSITIONS = {
    PrintJobStatus.QUEUED: {PrintJobStatus.RECEIVED, PrintJobStatus.CANCELLED},
    PrintJobStatus.RECEIVED: {
        PrintJobStatus.PRINTING,
        PrintJobStatus.WAITING_FOR_PRINTER,
        PrintJobStatus.FAILED,
        PrintJobStatus.CANCELLED,
    },
    PrintJobStatus.WAITING_FOR_PRINTER: {
        PrintJobStatus.PRINTING,
        PrintJobStatus.FAILED,
        PrintJobStatus.CANCELLED,
    },
    PrintJobStatus.PRINTING: {PrintJobStatus.COMPLETED, PrintJobStatus.FAILED},
    PrintJobStatus.COMPLETED: set(),
    PrintJobStatus.FAILED: set(),
    PrintJobStatus.CANCELLED: set(),
}

TERMINAL_STATUSES = {
    PrintJobStatus.COMPLETED,
    PrintJobStatus.FAILED,
    PrintJobStatus.CANCELLED,
}


def is_legal_transition(current: PrintJobStatus, next_status: PrintJobStatus) -> bool:
    if current == next_status:
        return True  # idempotent resend
    return next_status in LEGAL_TRANSITIONS[current]


def is_terminal(status: PrintJobStatus) -> bool:
    return status in TERMINAL_STATUSES

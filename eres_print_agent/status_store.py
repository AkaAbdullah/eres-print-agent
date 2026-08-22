"""A small JSON snapshot the running agent process writes on every state
change, so `eres-print-agent status`/`printers` (a separate, short-lived CLI
process) has something to read — there is no IPC channel into the running
service, only this file plus the SQLite queue.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from .config import STATUS_PATH


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def write_status(snapshot: Dict[str, Any]) -> None:
    STATUS_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = {**snapshot, "updatedAt": _now_iso()}
    tmp_path = STATUS_PATH.with_suffix(".json.tmp")
    tmp_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    tmp_path.replace(STATUS_PATH)  # atomic on both POSIX and Windows


def read_status() -> Optional[Dict[str, Any]]:
    if not STATUS_PATH.exists():
        return None
    try:
        return json.loads(STATUS_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None

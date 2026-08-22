"""Non-secret local configuration.

Per spec section 33 ("No Manual Reconfiguration"), the only fields kept
here are what pairing produces automatically (hubUrl, agentId) plus a log
level — there is nothing here a user is expected to hand-edit. The
*secret* (agentSecret) never lives in this file; see credentials.py.
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Optional


def _config_dir() -> Path:
    if sys.platform == "win32":
        base = os.environ.get("PROGRAMDATA", r"C:\ProgramData")
        return Path(base) / "ERES" / "PrintAgent"
    # macOS/Linux dev fallback — never used in the production Windows
    # deployment, only for running the agent locally against print-hub's
    # dev harness.
    return Path.home() / ".eres-print-agent"


CONFIG_DIR = _config_dir()
CONFIG_PATH = CONFIG_DIR / "config.json"
LOG_DIR = CONFIG_DIR / "logs"
DB_PATH = CONFIG_DIR / "queue.sqlite3"
STATUS_PATH = CONFIG_DIR / "status.json"


@dataclass
class AgentConfig:
    agentId: Optional[str] = None
    hubUrl: Optional[str] = None
    logLevel: str = "INFO"
    allowedDocumentHost: Optional[str] = None
    """Host component of hubUrl's paired web/ origin, derived at pairing
    time. print.job.documentUrl must resolve to this host — closes off an
    SSRF/arbitrary-fetch vector where a compromised or malicious hub could
    hand the agent a job pointing anywhere on the internet."""

    @property
    def is_paired(self) -> bool:
        return bool(self.agentId and self.hubUrl)


def load_config() -> AgentConfig:
    if not CONFIG_PATH.exists():
        return AgentConfig()
    try:
        data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return AgentConfig()
    known_fields = {f for f in AgentConfig.__dataclass_fields__}
    return AgentConfig(**{k: v for k, v in data.items() if k in known_fields})


def save_config(config: AgentConfig) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(asdict(config), indent=2), encoding="utf-8")


def ensure_directories() -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)

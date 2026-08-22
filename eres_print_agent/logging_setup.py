"""Structured logging with rotation and secret redaction.

Spec section 31: never log API tokens, passwords, or document contents.
Nothing in this codebase logs a raw PDF buffer, but agentSecret and
Authorization headers do pass through code paths that log request context
for debugging — this filter is a backstop so a future log line that
accidentally includes one gets scrubbed rather than shipped.
"""

from __future__ import annotations

import json
import logging
import logging.handlers
import re
import sys

from .config import LOG_DIR, ensure_directories

_AGENT_SECRET_PATTERN = re.compile(r"eres_agent_live_[A-Za-z0-9_\-]+")
_BEARER_TOKEN_PATTERN = re.compile(r"(Bearer\s+)[A-Za-z0-9_\-\.]+", re.IGNORECASE)


def _redact(message: str) -> str:
    redacted = _AGENT_SECRET_PATTERN.sub("eres_agent_live_[redacted]", message)
    redacted = _BEARER_TOKEN_PATTERN.sub(r"\1[redacted]", redacted)
    return redacted


class RedactingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        try:
            record.msg = _redact(str(record.msg))
        except Exception:
            pass
        return True


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload)


def configure_logging(level: str = "INFO") -> None:
    ensure_directories()

    root = logging.getLogger()
    root.setLevel(level)
    root.handlers.clear()

    file_handler = logging.handlers.RotatingFileHandler(
        LOG_DIR / "agent.log",
        maxBytes=10 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setFormatter(JsonFormatter())
    file_handler.addFilter(RedactingFilter())
    root.addHandler(file_handler)

    if sys.stdout is not None:
        stream_handler = logging.StreamHandler(sys.stdout)
        stream_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
        stream_handler.addFilter(RedactingFilter())
        root.addHandler(stream_handler)
